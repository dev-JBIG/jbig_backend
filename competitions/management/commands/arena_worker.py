import time

from django.core.management.base import BaseCommand

from competitions.models import Submission
from competitions.scoring import score_next


class Command(BaseCommand):
    help = 'Run the private grader. Restart with --retry-errors to recover failed jobs without charging again.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Drain currently queued jobs and exit.')
        parser.add_argument('--retry-errors', action='store_true')

    def handle(self, *args, **options):
        if options['retry_errors']:
            Submission.objects.filter(status=Submission.Status.ERROR).update(status=Submission.Status.QUEUED)
        scored = failed = 0
        try:
            while True:
                result = score_next()
                if result is None:
                    if options['once']:
                        break
                    time.sleep(2)
                elif result:
                    scored += 1
                    self.stdout.write('Arena: 채점 완료')
                else:
                    failed += 1
                    self.stderr.write('Arena: 채점 지연. 비공개 파일·버전을 확인한 후 --retry-errors로 복구하세요.')
        except KeyboardInterrupt:
            pass
        self.stdout.write(f'채점 완료 {scored}건, 복구 필요 {failed}건')
