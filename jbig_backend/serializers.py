from rest_framework import serializers
from .models import CalendarEvent

class CalendarEventSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = CalendarEvent
        fields = ['id', 'author', 'title', 'start', 'end', 'allDay', 'color', 'description']