import os
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.conf import settings
from html_serving.models import Award

class Command(BaseCommand):
    help = 'Scans the media/awards directory and populates the Award model'

    def handle(self, *args, **options):
        awards_dir = os.path.join(settings.MEDIA_ROOT, 'awards')
        if not os.path.exists(awards_dir) or not os.path.isdir(awards_dir):
            self.stdout.write(self.style.ERROR('media/awards directory not found.'))
            return

        html_files = [f for f in os.listdir(awards_dir) if f.endswith('.html')]

        for file_name in html_files:
            file_path = os.path.join(awards_dir, file_name)
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
                title = soup.title.string if soup.title else file_name
                award, created = Award.objects.get_or_create(
                    file_path=os.path.join('awards', file_name),
                    defaults={'title': title}
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created Award entry for {file_name}'))
                else:
                    # Update title if it has changed
                    if award.title != title:
                        award.title = title
                        award.save()
                        self.stdout.write(self.style.SUCCESS(f'Updated Award entry for {file_name}'))

        self.stdout.write(self.style.SUCCESS('Award entries updated successfully.'))
