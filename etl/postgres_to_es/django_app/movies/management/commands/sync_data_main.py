import os
import uuid
import logging
from typing import Iterator, List, Dict
import backoff
import psycopg2
from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import ConnectionError as ESConnectionError
from psycopg2.extras import DictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class State:
    def __init__(self, file_path: str = 'state.txt'):
        self.file_path = file_path
        self.last_id = uuid.UUID(int=0)  # Начальное значение

    def load(self) -> None:
        try:
            with open(self.file_path, 'r') as f:
                self.last_id = uuid.UUID(f.read().strip())
        except FileNotFoundError:
            pass

    def save(self) -> None:
        with open(self.file_path, 'w') as f:
            f.write(str(self.last_id))

@backoff.on_exception(backoff.expo, ESConnectionError, max_tries=10)
def get_es_connection() -> Elasticsearch:
    es_host = os.getenv('ES_HOST', 'http://localhost:9200')
    return Elasticsearch([es_host])

@backoff.on_exception(backoff.expo, psycopg2.OperationalError, max_tries=10)
def get_pg_connection():
    return psycopg2.connect(
        dbname=os.getenv('POSTGRES_DB'),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD'),
        host=os.getenv('POSTGRES_HOST'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        cursor_factory=DictCursor
    )

def fetch_data_from_pg(state: State, batch_size: int = 100) -> Iterator[List[Dict]]:
    """Извлекает данные из PostgreSQL порциями."""
    query = """
    SELECT
        fw.id,
        fw.title,
        fw.description,
        fw.rating AS imdb_rating,
        COALESCE(
            json_agg(DISTINCT jsonb_build_object('id', g.id, 'name', g.name)) 
            FILTER (WHERE g.id IS NOT NULL),
            '[]'
        ) AS genres,
        COALESCE(
            json_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name)) 
            FILTER (WHERE pfw.role = 'director'),
            '[]'
        ) AS directors,
        COALESCE(
            json_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name)) 
            FILTER (WHERE pfw.role = 'actor'),
            '[]'
        ) AS actors,
        COALESCE(
            json_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.full_name)) 
            FILTER (WHERE pfw.role = 'writer'),
            '[]'
        ) AS writers,
        array_remove(array_agg(DISTINCT p.full_name) 
            FILTER (WHERE pfw.role = 'director'), NULL) AS directors_names,
        array_remove(array_agg(DISTINCT p.full_name) 
            FILTER (WHERE pfw.role = 'actor'), NULL) AS actors_names,
        array_remove(array_agg(DISTINCT p.full_name) 
            FILTER (WHERE pfw.role = 'writer'), NULL) AS writers_names
    FROM film_work fw
    LEFT JOIN genre_film_work gfw ON fw.id = gfw.film_work_id
    LEFT JOIN genre g ON gfw.genre_id = g.id
    LEFT JOIN person_film_work pfw ON fw.id = pfw.film_work_id
    LEFT JOIN person p ON pfw.person_id = p.id
    WHERE fw.id > %s
    GROUP BY fw.id
    ORDER BY fw.id
    LIMIT %s;
    """

    with get_pg_connection() as conn:
        cursor = conn.cursor()
        while True:
            cursor.execute(query, (str(state.last_id), batch_size))
            rows = cursor.fetchall()
            if not rows:
                break
            yield rows
            state.last_id = rows[-1]['id']
            state.save()

def transform_data(rows: List[Dict]) -> Iterator[Dict]:
    """Преобразует данные для Elasticsearch."""
    for row in rows:
        doc = {
            'id': str(row['id']),
            'title': row['title'] or '',
            'imdb_rating': row['imdb_rating'] or 0.0,
            'description': row['description'] or '',
            'genres': [genre['name'] for genre in row['genres']],
            'directors_names': [name for name in row['directors_names'] if name != 'N/A'],
            'actors_names': [name for name in row['actors_names'] if name != 'N/A'],
            'writers_names': [name for name in row['writers_names'] if name != 'N/A'],
            'directors': row['directors'],
            'actors': row['actors'],
            'writers': row['writers'],
        }
        yield {'_index': 'movies', '_id': doc['id'], '_source': doc}

@backoff.on_exception(backoff.expo, ESConnectionError, max_tries=10)
def load_to_es(es: Elasticsearch, data: Iterator[Dict]) -> bool:
    """Загружает данные в Elasticsearch."""
    success, _ = helpers.bulk(es, data)
    return success == 0

def main():
    state = State()
    state.load()
    es = get_es_connection()

    for batch in fetch_data_from_pg(state):
        transformed = transform_data(batch)
        try:
            if load_to_es(es, transformed):
                logger.info(f"Processed {len(batch)} records")
        except Exception as e:
            logger.error(f"Error loading batch: {e}")
            continue

if __name__ == '__main__':
    main()
