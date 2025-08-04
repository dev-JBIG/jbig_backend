from rest_framework import serializers
from .models import Notion

class NotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notion
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

class NotionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notion
        fields = ('id', 'title', 'type', 'image', 'created_at')
