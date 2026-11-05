import uuid

from django.core.paginator import Paginator
from django.http import FileResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .csv_validation import ArenaError, MAX_UPLOAD_BYTES
from .files import participant_path
from .models import Competition, FinalResult, Submission
from .services import accept_submission, get_competition, participant_for, public_leaderboard, select_final, used_today


class ArenaMember(BasePermission):
    message = 'JBIG 회원으로 로그인한 뒤 이용해 주세요.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and user.is_verified)


def parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ArenaError('INVALID_REQUEST', '유효한 접수 번호가 필요합니다.') from None


def submission_data(submission, participant, competition):
    selected = participant.selected_submission_id == submission.pk
    return {
        'id': str(submission.pk), 'filename': submission.filename,
        'accepted_at': submission.accepted_at.isoformat(), 'status': submission.status,
        'public_rmse': submission.public_rmse, 'is_selected': selected,
        'private_rmse': submission.private_rmse if selected and competition.phase() == Competition.State.FINALIZED else None,
    }


class ArenaView(APIView):
    permission_classes = [ArenaMember]

    def handle_exception(self, exc):
        if isinstance(exc, ArenaError):
            return Response({'code': exc.code, 'message': exc.message, 'errors': exc.errors}, status=exc.status)
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response


class OverviewView(ArenaView):
    permission_classes = [AllowAny]

    def get(self, request):
        competition = get_competition()
        dataset = competition.dataset
        member = ArenaMember().has_permission(request, self)
        participant = participant_for(request.user, competition) if member else None
        used = used_today(participant) if participant else None
        return Response({
            'name': 'JBIG Big Data Arena', 'phase': competition.phase(),
            'starts_at': competition.starts_at, 'ends_at': competition.ends_at,
            'server_time': timezone.now(), 'finalized_at': competition.finalized_at,
            'daily_limit': competition.daily_limit, 'used_today': used,
            'remaining_today': max(0, competition.daily_limit - used) if used is not None else None,
            'max_upload_bytes': MAX_UPLOAD_BYTES, 'train_rows': dataset.train_rows if dataset else 107964,
            'test_rows': dataset.test_rows if dataset else 10213, 'data_version': dataset.version if dataset else None,
            'eligible': member, 'public_name': participant.public_name if participant else None,
        })


class DownloadView(ArenaView):
    def get(self, request, kind):
        competition = get_competition()
        if competition.phase() == Competition.State.PREPARING or not competition.dataset_id:
            raise ArenaError('NOT_OPEN', '대회가 개방되면 데이터를 내려받을 수 있습니다.', 409)
        path = participant_path(competition.dataset, kind)
        try:
            stream = path.open('rb')
        except OSError:
            raise ArenaError('DATA_UNAVAILABLE', '파일을 준비하고 있습니다. 운영진에게 문의해 주세요.', 503) from None
        return FileResponse(stream, as_attachment=True, filename=path.name, content_type='text/csv; charset=utf-8')


class SubmissionsView(ArenaView):
    def get(self, request):
        competition = get_competition()
        participant = participant_for(request.user, competition)
        query = Submission.objects.filter(participant=participant)
        key = request.query_params.get('request_key')
        if key:
            query = query.filter(request_key=parse_uuid(key))
        try:
            page_number = max(1, int(request.query_params.get('page', 1)))
        except ValueError:
            raise ArenaError('INVALID_PAGE', '페이지 번호를 확인해 주세요.') from None
        page = Paginator(query, 20).get_page(page_number)
        return Response({
            'count': page.paginator.count, 'page': page.number, 'pages': page.paginator.num_pages,
            'results': [submission_data(row, participant, competition) for row in page],
        })

    def post(self, request):
        key = parse_uuid(request.headers.get('Idempotency-Key'))
        upload = request.FILES.get('file')
        if not upload or set(request.FILES) != {'file'}:
            raise ArenaError('FILE_REQUIRED', '예측 결과 CSV 파일 한 개를 선택해 주세요.')
        if not upload.name.lower().endswith('.csv'):
            raise ArenaError('CSV_REQUIRED', '.csv 확장자의 파일을 제출해 주세요.')
        if upload.size > MAX_UPLOAD_BYTES:
            raise ArenaError('FILE_TOO_LARGE', 'CSV 파일은 5MB(5,000,000바이트) 이하여야 합니다.', 413)
        content = upload.read(MAX_UPLOAD_BYTES + 1)
        submission, created = accept_submission(request.user, content, upload.name, key)
        competition = get_competition()
        participant = participant_for(request.user, competition)
        return Response({
            'submission': submission_data(submission, participant, competition),
            'remaining_today': max(0, competition.daily_limit - used_today(participant)),
            'replayed': not created,
        }, status=202 if created else 200)


class SubmissionView(ArenaView):
    def get(self, request, submission_id):
        competition = get_competition()
        participant = participant_for(request.user, competition)
        submission = Submission.objects.filter(pk=submission_id, participant=participant).first()
        if not submission:
            raise ArenaError('NOT_FOUND', '제출 내역을 찾을 수 없습니다.', 404)
        return Response(submission_data(submission, participant, competition))


class FinalSelectionView(ArenaView):
    def put(self, request):
        competition = get_competition()
        participant = participant_for(request.user, competition)
        participant = select_final(participant, parse_uuid(request.data.get('submission_id')))
        return Response({'selected_submission_id': str(participant.selected_submission_id)})


class LeaderboardView(ArenaView):
    def get(self, request):
        competition = get_competition()
        final = competition.phase() == Competition.State.FINALIZED
        rows = []
        if final:
            for result in FinalResult.objects.select_related('participant', 'submission').all():
                rows.append({
                    'rank': result.rank, 'public_name': result.public_name, 'score': result.private_rmse,
                    'accepted_at': result.submission.accepted_at, 'is_me': result.participant.user_id == request.user.pk,
                })
        else:
            for rank, submission in enumerate(public_leaderboard(competition), start=1):
                rows.append({
                    'rank': rank, 'public_name': submission.participant.public_name, 'score': submission.public_rmse,
                    'accepted_at': submission.accepted_at, 'is_me': submission.participant.user_id == request.user.pk,
                })
        return Response({'phase': competition.phase(), 'metric': 'private_rmse' if final else 'public_rmse', 'results': rows})
