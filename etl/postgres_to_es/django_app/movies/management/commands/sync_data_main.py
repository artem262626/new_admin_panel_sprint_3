import time
import logging
from datetime import datetime, timezone
from typing import Iterator, List, Dict

import backoff
import psycopg2
from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import ConnectionError as ESConnectionError
from pydantic import BaseSettings, Field, AnyUrl
from psycopg2.extras import DictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    postgres_db: str = Field(..., env="POSTGRES_DB")
    postgres_user: str = Field(..., env="POSTGRES_USER")
    postgres_password: str = Field(..., env="POSTGRES_PASSWORD")
    postgres_host: str = Field("localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(5432, env="POSTGRES_PORT")
    es_host: AnyUrl = Field("http://localhost:9200", env="ES_HOST")
    sleep_interval: int = Field(60, env="SLEEP_INTERVAL")

    class Config:
        env_file = ".env"
        case_sensitive = False


class State:
    """Класс для управления состоянием последней обработки"""
    def __init__(self, file_path: str = 'state.json'):
        self.file_path = file_path
        self.last_modified = datetime.min.replace(tzinfo=timezone.utc)

    def load(self) -> None:
        try:
            with open(self.file_path, 'r') as f:
                self.last_modified = datetime.fromisoformat(f.read().strip())
        except (FileNotFoundError, ValueError):
            pass

    def save(self) -> None:
        with open(self.file_path, 'w') as f:
            f.write(self.last_modified.isoformat())


@backoff.on_exception(backoff.expo, ESConnectionError, max_tries=10)
def get_es_connection(settings: Settings) -> Elasticsearch:
    """Установка соединения с Elasticsearch"""
    return Elasticsearch([str(settings.es_host)])


@backoff.on_exception(backoff.expo, psycopg2.OperationalError, max_tries=10)
def get_pg_connection(settings: Settings):
    return psycopg2.connect(
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        cursor_factory=DictCursor
    )


def fetch_data_from_pg(
    state: State,
    settings: Settings,
    batch_size: int = 100
) -> Iterator[List[Dict]]:
    """Извлечение данных из PostgreSQL с пагинацией"""
    query = """
        SELECT
            fw.id,
            fw.title,
            fw.description,
            fw.rating AS imdb_rating,
            fw.modified,
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
            array_remove(
                array_agg(DISTINCT p.full_name)
                FILTER (WHERE pfw.role = 'director'),
                NULL
            ) AS directors_names,
            array_remove(
                array_agg(DISTINCT p.full_name)
                FILTER (WHERE pfw.role = 'actor'),
                NULL
            ) AS actors_names,
            array_remove(
                array_agg(DISTINCT p.full_name)
                FILTER (WHERE pfw.role = 'writer'),
                NULL
            ) AS writers_names
        FROM film_work fw
        LEFT JOIN genre_film_work gfw ON fw.id = gfw.film_work_id
        LEFT JOIN genre g ON gfw.genre_id = g.id
        LEFT JOIN person_film_work pfw ON fw.id = pfw.film_work_id
        LEFT JOIN person p ON pfw.person_id = p.id
        WHERE fw.modified > %s
        GROUP BY fw.id, fw.modified
        ORDER BY fw.modified, fw.id
        LIMIT %s;
    """

    with get_pg_connection(settings) as conn:
        cursor = conn.cursor()
        while True:
            cursor.execute(query, (state.last_modified, batch_size))
            rows = cursor.fetchall()
            if not rows:
                break

            max_modified = max(row['modified'] for row in rows)
            if max_modified > state.last_modified:
                state.last_modified = max_modified
                state.save()

            yield rows


def transform_data(rows: List[Dict]) -> Iterator[Dict]:
    """Трансформация данных для Elasticsearch"""
    for row in rows:
        doc = {
            'id': str(row['id']),
            'title': row.get('title', ''),
            'imdb_rating': float(row['imdb_rating']) if row['imdb_rating'] else 0.0,
            'description': row.get('description', ''),
            'genres': [genre['name'] for genre in row['genres'] if genre],
            'directors_names': list(filter(None, row['directors_names'])),
            'actors_names': list(filter(None, row['actors_names'])),
            'writers_names': list(filter(None, row['writers_names'])),
            'directors': [
                {'id': str(d['id']), 'name': d['name']}
                for d in row['directors'] if d.get('id')
            ],
            'actors': [
                {'id': str(a['id']), 'name': a['name']}
                for a in row['actors'] if a.get('id')
            ],
            'writers': [
                {'id': str(w['id']), 'name': w['name']}
                for w in row['writers'] if w.get('id')
            ],
        }
        yield {
            '_index': 'movies',
            '_id': doc['id'],
            '_source': doc
        }


@backoff.on_exception(backoff.expo, ESConnectionError, max_tries=10)
def load_to_es(es: Elasticsearch, data: Iterator[Dict]) -> bool:
    """Загрузка данных в Elasticsearch с обработкой ошибок"""
    try:
        success_count, errors = helpers.bulk(es, data, stats_only=False)

        if errors:
            logger.error(f"Failed to index {len(errors)} documents:")
            for error in errors:
                logger.error(
                    f"Document ID: {error['index']['_id']}, "
                    f"Error: {error['index']['error']['reason']}"
                )

        logger.info(f"Successfully indexed {success_count} documents")
        return success_count > 0

    except Exception as e:
        logger.error(f"Bulk upload failed: {str(e)}")
        return False


def main():
    """Основной цикл обработки"""
    try:
        settings = Settings()
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        raise

    state = State()
    es = get_es_connection(settings)

    try:
        while True:
            state.load()
            total_processed = 0

            try:
                for batch in fetch_data_from_pg(state, settings):
                    transformed = transform_data(batch)
                    if load_to_es(es, transformed):
                        total_processed += len(batch)
                        logger.info(f"Processed batch of {len(batch)} records")

                logger.info(f"Total processed: {total_processed}")
                logger.info(f"Next run in {settings.sleep_interval}s...")
                time.sleep(settings.sleep_interval)

            except Exception as e:
                logger.error(f"Processing error: {e}", exc_info=True)
                time.sleep(60)

    except KeyboardInterrupt:
        logger.info("ETL process stopped by user")
    finally:
        if es:
            es.close()
        logger.info("Service shutdown completed")


if __name__ == '__main__':
    main()
