import csv
import io
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from competitions.files import private_root
from competitions.models import Participant, Submission
from competitions.scoring import score_next
from competitions.services import accept_submission, get_competition


class Command(BaseCommand):
    help = 'Server-only golden/shuffled-label verification, using an unloginable test account excluded from rankings.'

    def handle(self, *args, **options):
        competition = get_competition()
        if not competition.dataset_id:
            raise CommandError('먼저 arena_setup을 실행하세요.')
        user, created = get_user_model().objects.get_or_create(
            email='arena-verification@local.invalid', defaults={'username': 'Arena 서버 검증', 'is_active': False},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=['password'])
        if user.is_active or user.has_usable_password():
            raise CommandError('기존 일반 계정을 서버 검증 계정으로 사용할 수 없습니다.')
        participant, created = Participant.objects.get_or_create(competition=competition, user=user, defaults={'is_test': True})
        if not participant.is_test:
            raise CommandError('검증용 이메일이 일반 참가자로 사용되고 있습니다.')
        path = private_root('ARENA_GRADING_ROOT') / competition.dataset_id / 'test_labels.csv'
        with path.open(encoding='utf-8-sig', newline='') as stream:
            labels = list(csv.DictReader(stream))
        submissions = []
        for kind, rows in [('golden', labels), ('shuffled', sorted(labels, key=lambda row: row['reservation_id'], reverse=True))]:
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(['reservation_id', 'adr'])
            writer.writerows((row['reservation_id'], row['adr']) for row in rows)
            key = uuid.uuid5(uuid.NAMESPACE_URL, f'arena-verify/{competition.dataset_id}/{kind}')
            submission, _ = accept_submission(user, output.getvalue().encode(), f'{kind}-server-verification.csv', key, verification=True)
            submissions.append(submission)
        while score_next() is not None:
            pass
        for submission in submissions:
            submission.refresh_from_db()
            if submission.status != Submission.Status.SCORED or submission.public_rmse != 0 or submission.private_rmse != 0:
                raise CommandError('0점 검증에 실패했습니다. 비공개 평가 파일과 채점 상태를 확인하세요.')
        self.stdout.write('10,213 ID 검증: 정답·순서 변경 제출 모두 Public RMSE=0, Private RMSE=0. 검증 계정은 리더보드에서 제외됩니다.')
