from django.contrib import admin
from .models import CalendarEvent

@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'start', 'end', 'allDay')
    search_fields = ('title', 'author__username')
    list_filter = ('start', 'allDay')
    raw_id_fields = ('author',)
