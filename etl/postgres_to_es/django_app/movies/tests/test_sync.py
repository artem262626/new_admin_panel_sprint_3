from django.test import TestCase
from elasticsearch import Elasticsearch
from ..models import Movie, SyncState

class DataSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Movie.objects.create(
            title="Test Movie",
            description="Test Description",
            imdb_rating=7.5,
            genres=["Action"],
            directors=[{"id": "1", "name": "Test Director"}],
            actors=[{"id": "2", "name": "Test Actor"}],
            writers=[{"id": "3", "name": "Test Writer"}]
        )

    def test_es_index_contains_data(self):
        es = Elasticsearch(['http://localhost:9200'])
        result = es.search(index='movies', body={"query": {"match_all": {}}})
        self.assertGreater(result['hits']['total']['value'], 0)

    def test_sync_state_updated(self):
        initial_count = SyncState.objects.count()
        from ..management.commands.sync_data import Command
        Command().handle()
        self.assertGreater(SyncState.objects.count(), initial_count)
