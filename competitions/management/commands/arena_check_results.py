from django.core.management.base import BaseCommand, CommandError

from competitions.models import Competition, FinalResult
from competitions.scoring import evaluate
from competitions.services import get_competition


class Command(BaseCommand):
    help = 'Recompute frozen final results from private source files and check scores, ordering and versions.'

    def handle(self, *args, **options):
        competition = get_competition()
        if competition.state != Competition.State.FINALIZED:
            raise CommandError('최종 결과를 확정한 뒤 재현 검증을 실행하세요.')
        computed = []
        for result in FinalResult.objects.select_related('submission__dataset', 'submission__participant').all():
            try:
                public, private = evaluate(result.submission)
            except Exception:
                raise CommandError('최종 제출의 원본 파일 또는 평가 버전을 확인할 수 없습니다.') from None
            if public != result.submission.public_rmse or private != result.private_rmse or private != result.submission.private_rmse:
                raise CommandError('재계산한 점수가 고정된 최종 결과와 일치하지 않습니다.')
            computed.append((private, result.submission.accepted_at, str(result.submission_id), result.rank))
        if any(rank != row[3] for rank, row in enumerate(sorted(computed), start=1)):
            raise CommandError('재계산한 최종 순위가 고정된 결과와 일치하지 않습니다.')
        self.stdout.write(f'최종 결과 {len(computed)}명 재현 완료. 데이터 버전 {competition.dataset_id}, 평가 버전 {competition.dataset.evaluator_version}.')
