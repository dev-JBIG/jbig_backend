from django.contrib import admin
from .models import CalendarEvent, Popup

@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'start', 'end', 'allDay')
    search_fields = ('title', 'author__username')
    list_filter = ('start', 'allDay')
    raw_id_fields = ('author',)


@admin.register(Popup)
class PopupAdmin(admin.ModelAdmin):
    list_display = ('title', 'start_date', 'end_date', 'is_active', 'order', 'created_by', 'created_at')
    search_fields = ('title', 'content', 'created_by__username')
    list_filter = ('is_active', 'start_date', 'end_date', 'created_at')
    raw_id_fields = ('created_by',)
    ordering = ('order', '-created_at')
