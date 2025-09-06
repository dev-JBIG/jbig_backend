from django.core.management.base import BaseCommand
from jbig_backend.models import CalendarEvent
from django.contrib.auth import get_user_model
from datetime import datetime

class Command(BaseCommand):
    help = 'Seeds the database with sample calendar events.'

    def handle(self, *args, **kwargs):
        self.stdout.write('Deleting old calendar events...')
        CalendarEvent.objects.all().delete()

        User = get_user_model()
        
        # Get or create a staff user for the event author
        author, created = User.objects.get_or_create(
            username='staff_tester',
            defaults={'is_staff': True, 'email': 'staff@example.com'}
        )
        if created:
            author.set_password('password')
            author.save()
            self.stdout.write(self.style.SUCCESS('Created a temporary staff user.'))

        self.stdout.write('Creating new calendar events...')

        events = [
            # Events in 2024
            {'title': 'Event 2024-1', 'start': datetime(2024, 3, 15), 'end': datetime(2024, 3, 17), 'color': '#FF0000', 'description': 'Event in March 2024'},
            {'title': 'Event 2024-2 (All Day)', 'start': datetime(2024, 8, 5), 'allDay': True, 'color': '#00FF00', 'description': 'All day event in Aug'},
            
            # Events in 2025
            {'title': 'Event 2025-1', 'start': datetime(2025, 1, 10), 'end': datetime(2025, 1, 12), 'color': '#0000FF', 'description': 'Event in Jan 2025'},
            {'title': 'Event 2025-2 (Spanning)', 'start': datetime(2025, 12, 20), 'end': datetime(2026, 1, 5), 'color': '#FFFF00', 'description': 'Event spanning years'},

            # Events in 2026
            {'title': 'Event 2026-1', 'start': datetime(2026, 2, 20), 'end': None, 'color': '#00FFFF', 'description': 'Event in Feb 2026'},
        ]

        for event_data in events:
            CalendarEvent.objects.create(author=author, **event_data)

        self.stdout.write(self.style.SUCCESS('Successfully seeded the calendar with 5 events.'))
