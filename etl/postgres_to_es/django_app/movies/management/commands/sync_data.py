# sync_data.py
from django.core.management.base import BaseCommand
from django.db import transaction, OperationalError
from elasticsearch import exceptions as es_errors
import backoff
from ...models import Movie, SyncState
from ...documents import MovieDocument

class Command(BaseCommand):
    help = 'Sync data from Postgres to Elasticsearch with resilience'

    @backoff.on_exception(
        backoff.expo,
        (OperationalError, es_errors.ConnectionError),
        max_tries=10
    )
    def handle(self, *args, **options):
        last_state = SyncState.objects.last()
        last_id = last_state.last_processed_id if last_state else None
        
        qs = Movie.objects.all().order_by('id')
        if last_id:
            qs = qs.filter(id__gt=last_id)

        batch_size = 500
        for offset in range(0, qs.count(), batch_size):
            batch = qs[offset:offset+batch_size]
            self.process_batch(batch)

    @backoff.on_exception(
        backoff.expo,
        (es_errors.ConnectionError, OperationalError),
        max_tries=5
    )
    def process_batch(self, batch):
        docs = [MovieDocument(**movie.to_dict()) for movie in batch]
        MovieDocument.bulk(docs)
        
        with transaction.atomic():
            SyncState.objects.update_or_create(
                defaults={'last_processed_id': batch.last().id}
            )
