from rest_framework import serializers
from .models import CalendarEvent, Popup

class CalendarEventSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = CalendarEvent
        fields = ['id', 'author', 'title', 'start', 'end', 'allDay', 'color', 'description']


class PopupSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Popup
        fields = [
            'id', 'title', 'content', 'start_date', 'end_date', 
            'is_active', 'created_at', 'updated_at', 
            'created_by', 'created_by_username', 'order'
        ]
        read_only_fields = ['created_at', 'updated_at', 'created_by']