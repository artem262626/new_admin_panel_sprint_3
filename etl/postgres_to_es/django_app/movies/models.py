from django.db import models
import uuid

class Movie(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField()
    imdb_rating = models.FloatField()
    genres = models.JSONField(default=list)
    directors = models.JSONField(default=list)
    actors = models.JSONField(default=list)
    writers = models.JSONField(default=list)
    directors_names = models.TextField(blank=True)
    actors_names = models.TextField(blank=True)
    writers_names = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "imdb_rating": self.imdb_rating,
            "genres": self.genres,
            "directors": self.directors,
            "actors": self.actors,
            "writers": self.writers
        }

class SyncState(models.Model):
    last_processed_id = models.UUIDField()
    timestamp = models.DateTimeField(auto_now=True)
