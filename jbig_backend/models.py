from django.db import models
from django.conf import settings

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