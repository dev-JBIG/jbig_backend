import hashlib
import re
import random
import time
from zoneinfo import ZoneInfo

from django.db import DatabaseError, OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from .csv_validation import ArenaError, validate_submission
from .files import read_expected_ids, submission_path, write_private
from .models import Competition, DailyQuota, FinalResult, Participant, Submission


KST = ZoneInfo('Asia/Seoul')


def get_competition():
    return Competition.objects.select_related('dataset').get(pk=1)


def participant_for(user, competition):
    return Participant.objects.get_or_create(user=user, competition=competition)[0]


def used_today(participant, now=None):
    day = (now or timezone.now()).astimezone(KST).date()
    return DailyQuota.objects.filter(participant=participant, day=day).values_list('used', flat=True).first() or 0


def accept_submission(user, content, filename, request_key, *, verification=False):
    content_hash = hashlib.sha256(content).hexdigest()
    for attempt in range(8):
        try:
            return _prepare_and_accept(user, content, content_hash, filename, request_key, verification)
        except OperationalError as exc:
            if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower() or attempt == 7:
                raise ArenaError('ACCEPT_UNAVAILABLE', '접수 상태를 확인하지 못했습니다. 같은 파일로 다시 시도해 주세요.', 503) from None
            time.sleep(random.uniform(0.01, 0.03) * (2 ** min(attempt, 4)))


def _prepare_and_accept(user, content, content_hash, filename, request_key, verification):
    competition = get_competition()
    participant = participant_for(user, competition)
    existing = Submission.objects.filter(participant=participant, request_key=request_key).first()
    if existing:
        return check_replay(existing, content_hash), False
    if not competition.dataset_id:
        raise ArenaError('NOT_OPEN', '대회가 아직 준비 중입니다.', 409)
    validate_submission(content, set(read_expected_ids(competition.dataset)))
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename.replace('\\', '/').rsplit('/', 1)[-1])[:160] or 'submission.csv'
    return _accept(participant, competition.dataset_id, content, content_hash, filename, request_key, verification)


def lock_competition():
    if connection.vendor == 'sqlite':
        # Acquire the write lock before any transactional reads (SQLite has no row locks).
        Competition.objects.filter(pk=1).update(id=F('id'))
    return Competition.objects.select_for_update().get(pk=1)


def check_replay(existing, content_hash):
    if existing.content_hash != content_hash:
        raise ArenaError('REQUEST_CONFLICT', '같은 접수 요청에 다른 파일이 들어왔습니다. 새 파일을 선택해 다시 제출해 주세요.', 409)
    return existing


def _accept(participant, dataset_id, content, content_hash, filename, request_key, verification):
    written = None
    try:
        with transaction.atomic():
            competition = lock_competition()
            existing = Submission.objects.filter(participant=participant, request_key=request_key).first()
            if existing:
                return check_replay(existing, content_hash), False
            now = timezone.now()
            if verification:
                if not participant.is_test:
                    raise ArenaError('TEST_ONLY', '서버 검증 계정만 사용할 수 있습니다.', 403)
            elif competition.phase(now) != Competition.State.OPEN:
                raise ArenaError('NOT_OPEN', '현재 제출을 접수하지 않습니다. 대회 상태와 일정을 확인해 주세요.', 409)
            if competition.dataset_id != dataset_id:
                raise ArenaError('DATA_CHANGED', '데이터 버전이 변경되었습니다. 페이지를 새로고침해 주세요.', 409)
            day = now.astimezone(KST).date()
            quota, _ = DailyQuota.objects.get_or_create(participant=participant, day=day)
            updated = DailyQuota.objects.filter(pk=quota.pk, used__lt=competition.daily_limit).update(used=F('used') + 1)
            if not updated:
                raise ArenaError('DAILY_LIMIT', '오늘 제출 기회를 모두 사용했습니다. 일일 한도는 KST 자정에 갱신됩니다.', 429)
            submission = Submission(
                participant=participant, dataset_id=dataset_id, request_key=request_key,
                content_hash=content_hash, filename=filename, accepted_at=now, quota_day=day,
            )
            path = submission_path(submission)
            try:
                write_private(path, content)
                written = path
            except OSError:
                raise ArenaError('STORAGE_UNAVAILABLE', '파일을 안전하게 저장하지 못했습니다. 제출 횟수는 차감되지 않았습니다.', 503) from None
            submission.save(force_insert=True)
        return submission, True
    except Exception:
        if written:
            try:
                if not Submission.objects.filter(pk=submission.pk).exists():
                    written.unlink(missing_ok=True)
            except (DatabaseError, OSError):
                # A lost COMMIT acknowledgement must never remove an accepted file.
                pass
        raise


def select_final(participant, submission_id):
    with transaction.atomic():
        competition = lock_competition()
        if competition.phase() != Competition.State.OPEN:
            raise ArenaError('SELECTION_CLOSED', '마감 전 진행 기간에만 최종 평가용 제출을 선택할 수 있습니다.', 409)
        participant = Participant.objects.select_for_update().get(pk=participant.pk)
        submission = Submission.objects.filter(pk=submission_id, participant=participant).first()
        if not submission:
            raise ArenaError('NOT_FOUND', '제출 내역을 찾을 수 없습니다.', 404)
        participant.selected_submission = submission
        participant.save(update_fields=['selected_submission'])
        return participant


def public_leaderboard(competition):
    rows, seen = [], set()
    submissions = Submission.objects.filter(
        participant__competition=competition, participant__is_test=False, status=Submission.Status.SCORED,
    ).select_related('participant').order_by('public_rmse', 'accepted_at', 'id')
    for submission in submissions:
        if submission.participant_id not in seen:
            seen.add(submission.participant_id)
            rows.append(submission)
    return rows


def finalize():
    with transaction.atomic():
        competition = lock_competition()
        if competition.state == Competition.State.FINALIZED:
            return FinalResult.objects.count()
        if competition.phase() != Competition.State.CLOSED:
            raise ArenaError('NOT_CLOSED', '접수가 마감된 후에 최종 결과를 확정할 수 있습니다.', 409)
        eligible = Submission.objects.filter(participant__competition=competition, participant__is_test=False)
        if eligible.exclude(status=Submission.Status.SCORED).exists():
            raise ArenaError('SCORING_PENDING', '미완료 채점이 있습니다. 서버 오류를 복구하고 모든 채점을 마친 뒤 다시 실행하세요.', 409)
        chosen = []
        for participant in Participant.objects.filter(competition=competition, is_test=False).select_related('selected_submission'):
            submission = participant.selected_submission
            reason = 'manual'
            if submission is None:
                submission = eligible.filter(participant=participant).order_by('public_rmse', 'accepted_at', 'id').first()
                reason = 'automatic'
            if submission is not None:
                chosen.append((submission, participant, reason))
        chosen.sort(key=lambda item: (item[0].private_rmse, item[0].accepted_at, str(item[0].pk)))
        for rank, (submission, participant, reason) in enumerate(chosen, start=1):
            FinalResult.objects.create(
                participant=participant, submission=submission, rank=rank,
                public_name=participant.public_name, private_rmse=submission.private_rmse, selection_reason=reason,
            )
            if reason == 'automatic':
                participant.selected_submission = submission
                participant.save(update_fields=['selected_submission'])
        competition.state = Competition.State.FINALIZED
        competition.finalized_at = timezone.now()
        competition.save(update_fields=['state', 'finalized_at'])
        return len(chosen)
