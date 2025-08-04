from django.contrib import admin
from .models import Notion

@admin.register(Notion)
class NotionAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'created_at', 'updated_at')
    list_filter = ('type',)
    search_fields = ('title',)