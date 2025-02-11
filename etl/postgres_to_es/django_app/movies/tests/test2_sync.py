from django.test import TestCase
from movies.models import SyncState

class SyncStateTest(TestCase):
    def test_last_processed_id(self):
        last_state = SyncState.objects.last()
        self.assertEqual(
            str(last_state.last_processed_id), 
            '479f20b0-58d1-4f16-8944-9b82f5b1f22a'
        )
