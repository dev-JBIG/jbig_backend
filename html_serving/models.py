from django.db import models

class Notion(models.Model):
    title = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512, unique=True)

    def __str__(self):
        return self.title
