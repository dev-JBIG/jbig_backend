from django.db import models


class Notion(models.Model):
    """Deprecated - DB 호환성 위해 유지"""
    title = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512, unique=True)

    class Meta:
        verbose_name = '[Deprecated] Notion'
        verbose_name_plural = '[Deprecated] Notion'

    def __str__(self):
        return self.title
