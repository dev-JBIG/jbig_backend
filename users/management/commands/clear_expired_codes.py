from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from users.models import User

class Command(BaseCommand):
    help = 'Clears expired verification codes from User accounts.'

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(minutes=3)
        expired_users = User.objects.filter(
            verification_code__isnull=False,
            verification_code_sent_at__lt=threshold
        )
        count = expired_users.count()
        expired_users.update(verification_code=None, verification_code_sent_at=None)
        self.stdout.write(self.style.SUCCESS(f'Successfully cleared {count} expired verification codes.'))
