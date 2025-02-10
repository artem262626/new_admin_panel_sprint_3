# documents.py
from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from .models import Movie

@registry.register_document
class MovieDocument(Document):
    id = fields.KeywordField()
    imdb_rating = fields.FloatField()
    title = fields.TextField(
        analyzer='ru_en',
        fields={'raw': fields.KeywordField()}
    )
    description = fields.TextField(analyzer='ru_en')
    genres = fields.KeywordField()
    
    directors = fields.NestedField(properties={
        'id': fields.KeywordField(),
        'name': fields.TextField(analyzer='ru_en')
    })
    
    actors = fields.NestedField(properties={
        'id': fields.KeywordField(),
        'name': fields.TextField(analyzer='ru_en')
    })
    
    writers = fields.NestedField(properties={
        'id': fields.KeywordField(),
        'name': fields.TextField(analyzer='ru_en')
    })

    class Index:
        name = 'movies'
        settings = {
            'number_of_shards': 1,
            'number_of_replicas': 0
        }

    class Django:
        model = Movie
        fields = [
            'directors_names',  # Эти поля будут автоматически взяты из модели
            'actors_names',
            'writers_names'
        ]
