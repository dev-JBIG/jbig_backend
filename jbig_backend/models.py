from django.db import models
from django.conf import settings


class SiteSettings(models.Model):
    key = models.CharField(max_length=100, unique=True, primary_key=True)
    value = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'site_settings'
        verbose_name = '사이트 설정'
        verbose_name_plural = '사이트 설정'

    def __str__(self):
        return f"{self.key}: {self.value[:50]}"

    @classmethod
    def get(cls, key, default=''):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value):
        obj, _ = cls.objects.update_or_create(key=key, defaults={'value': value})
        return obj


class CalendarEvent(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    allDay = models.BooleanField(default=False)
    color = models.CharField(max_length=7)
    description = models.CharField(max_length=20)

    def __str__(self):
        return self.title