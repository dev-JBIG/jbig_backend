from django.core.management.base import BaseCommand
from boards.models import Attachment
import os
from django.conf import settings

class Command(BaseCommand):
    help = 'Deletes orphaned attachment files (not linked to any post).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting orphaned attachment cleanup...'))
        
        orphaned_attachments = Attachment.objects.filter(post__isnull=True)
        count = orphaned_attachments.count()
        
        for attachment in orphaned_attachments:
            # The delete method of the Attachment model is overridden to handle file deletion
            attachment.delete() 
            self.stdout.write(f'Deleted attachment: {attachment.filename} (ID: {attachment.id})')
            
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} orphaned attachments.'))
