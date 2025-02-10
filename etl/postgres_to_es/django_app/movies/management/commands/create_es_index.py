from django.core.management.base import BaseCommand
from elasticsearch import Elasticsearch, exceptions as es_errors
import backoff
import json

INDEX_NAME = 'movies'
INDEX_BODY = {
    "settings": {
        "refresh_interval": "1s",
        "analysis": {
            "filter": {
                "english_stop": {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "english_possessive_stemmer": {"type": "stemmer", "language": "possessive_english"},
                "russian_stop": {"type": "stop", "stopwords": "_russian_"},
                "russian_stemmer": {"type": "stemmer", "language": "russian"}
            },
            "analyzer": {
                "ru_en": {
                    "tokenizer": "standard",
                    "filter": [
                        "lowercase",
                        "english_stop",
                        "english_stemmer",
                        "english_possessive_stemmer",
                        "russian_stop",
                        "russian_stemmer"
                    ]
                }
            }
        }
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "imdb_rating": {"type": "float"},
            "genres": {"type": "keyword"},
            "title": {
                "type": "text",
                "analyzer": "ru_en",
                "fields": {"raw": {"type": "keyword"}}
            },
            "description": {"type": "text", "analyzer": "ru_en"},
            "directors_names": {"type": "text", "analyzer": "ru_en"},
            "actors_names": {"type": "text", "analyzer": "ru_en"},
            "writers_names": {"type": "text", "analyzer": "ru_en"},
            "directors": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"}
                }
            },
            "actors": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"}
                }
            },
            "writers": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"}
                }
            }
        }
    }
}

class Command(BaseCommand):
    help = 'Create Elasticsearch movies index with full mapping'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.es = Elasticsearch(['http://localhost:9200'])

    @backoff.on_exception(
        backoff.expo,
        (es_errors.ConnectionError, es_errors.TransportError),
        max_tries=10,
        max_time=30
    )
    def handle(self, *args, **options):
        try:
            # Проверка существования индекса
            if self.es.indices.exists(index=INDEX_NAME):
                if options['force']:
                    self.stdout.write(self.style.WARNING(f'Deleting existing index: {INDEX_NAME}'))
                    self.es.indices.delete(index=INDEX_NAME)
                else:
                    self.stdout.write(self.style.WARNING(f'Index {INDEX_NAME} already exists'))
                    return

            # Создание индекса
            self.es.indices.create(
                index=INDEX_NAME,
                body=INDEX_BODY,
                ignore=400
            )

            # Проверка создания
            if self.es.indices.exists(index=INDEX_NAME):
                self.stdout.write(self.style.SUCCESS(f'Successfully created index: {INDEX_NAME}'))
                self.stdout.write(json.dumps(
                    self.es.indices.get_mapping(index=INDEX_NAME),
                    indent=2
                ))
            else:
                raise es_errors.RequestError('Index creation failed')

        except es_errors.RequestError as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            if e.error == 'resource_already_exists_exception':
                self.stdout.write(self.style.NOTICE('Use --force to overwrite existing index'))

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreate index if exists'
        )

