from django.core.management.base import BaseCommand
from django.conf import settings
from boards.models import Post
from bs4 import BeautifulSoup
import os


class Command(BaseCommand):
    help = "Migrate Post.content_html FileField contents into TextField by reading existing files. Safe to re-run."

    def handle(self, *args, **options):
        migrated = 0
        missing = 0
        skipped = 0

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        for post in Post.objects.all().iterator():
            raw = post.content_html

            # Case 1: Looks like real HTML already
            if isinstance(raw, str) and raw and ('<' in raw and '>' in raw):
                skipped += 1
                continue

            # Case 2: String that is likely a relative file path saved from previous FileField
            file_path = None
            if isinstance(raw, str) and raw:
                rel = raw.lstrip('/')
                if media_root:
                    file_path = os.path.join(str(media_root), rel)
                else:
                    file_path = rel  # best effort

            if not file_path or not os.path.exists(file_path):
                missing += 1
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    html = f.read()
                soup = BeautifulSoup(html, 'html.parser')
                post.content_html = str(soup)
                post.save(update_fields=['content_html'])
                migrated += 1
            except Exception:
                missing += 1

        self.stdout.write(self.style.SUCCESS(
            f"Migration complete. migrated={migrated}, missing_or_failed={missing}, skipped_already_text={skipped}"
        ))
