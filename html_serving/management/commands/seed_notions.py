import os
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.conf import settings
from html_serving.models import Notion

class Command(BaseCommand):
    help = 'Scans the media/notion directory and populates the Notion model'

    def handle(self, *args, **options):
        notion_dir = os.path.join(settings.MEDIA_ROOT, 'notion')
        if not os.path.exists(notion_dir) or not os.path.isdir(notion_dir):
            self.stdout.write(self.style.ERROR('media/notion directory not found.'))
            return

        html_files = [f for f in os.listdir(notion_dir) if f.endswith('.html')]

        for file_name in html_files:
            file_path = os.path.join(notion_dir, file_name)
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
                title = soup.title.string if soup.title else file_name
                notion, created = Notion.objects.get_or_create(
                    file_path=os.path.join('notion', file_name),
                    defaults={'title': title}
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created Notion entry for {file_name}'))
                else:
                    # Update title if it has changed
                    if notion.title != title:
                        notion.title = title
                        notion.save()
                        self.stdout.write(self.style.SUCCESS(f'Updated Notion entry for {file_name}'))

        self.stdout.write(self.style.SUCCESS('Notion entries updated successfully.'))
