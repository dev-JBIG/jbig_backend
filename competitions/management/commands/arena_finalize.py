from django.core.management.base import BaseCommand, CommandError

from competitions.csv_validation import ArenaError
from competitions.services import finalize


class Command(BaseCommand):
    help = 'Freeze selected submissions and publish the final Private leaderboard after closing.'

    def handle(self, *args, **options):
        try:
            count = finalize()
        except ArenaError as exc:
            raise CommandError(exc.message) from None
        self.stdout.write(f'최종 결과 {count}명 확정. 조별 시상은 운영진이 별도로 판별합니다.')
