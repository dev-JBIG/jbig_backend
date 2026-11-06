import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class DatasetVersion(models.Model):
    version = models.SlugField(max_length=64, primary_key=True)
    train_rows = models.PositiveIntegerField()
    test_rows = models.PositiveIntegerField()
    public_rows = models.PositiveIntegerField()
    private_rows = models.PositiveIntegerField()
    hashes = models.JSONField()
    evaluator_version = models.CharField(max_length=40, default='adr-rmse-v1')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.version


class Competition(models.Model):
    class State(models.TextChoices):
        PREPARING = 'preparing', '준비 중'
        OPEN = 'open', '진행'
        CLOSED = 'closed', '마감'
        FINALIZED = 'finalized', '최종 결과 확정'

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PREPARING)
    starts_at = models.DateTimeField(null=True, blank=True, verbose_name='시작 시각')
    ends_at = models.DateTimeField(null=True, blank=True, verbose_name='마감 시각')
    daily_limit = models.PositiveSmallIntegerField(default=5, verbose_name='일일 제출 한도')
    dataset = models.ForeignKey(DatasetVersion, null=True, blank=True, on_delete=models.PROTECT)
    finalized_at = models.DateTimeField(null=True, blank=True, editable=False)

    def __str__(self):
        return 'JBIG Big Data Arena'

    def phase(self, now=None):
        now = now or timezone.now()
        if self.state in (self.State.CLOSED, self.State.FINALIZED):
            return self.state
        if self.state != self.State.OPEN or not self.dataset_id or not self.starts_at or not self.ends_at:
            return self.State.PREPARING
        if now >= self.ends_at:
            return self.State.CLOSED
        return self.State.OPEN if now >= self.starts_at else self.State.PREPARING

    def clean(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError('마감 시각은 시작 시각보다 늦어야 합니다.')
        if self.state == self.State.OPEN and not all((self.starts_at, self.ends_at, self.dataset_id)):
            raise ValidationError('진행 상태에는 데이터 버전과 시작·마감 시각이 필요합니다.')
        if self.daily_limit < 1:
            raise ValidationError('일일 제출 한도는 1 이상이어야 합니다.')
        previous = Competition.objects.filter(pk=self.pk).first()
        if previous and previous.dataset_id != self.dataset_id and Submission.objects.exists():
            raise ValidationError('접수된 제출이 있어 평가 데이터 버전을 바꿀 수 없습니다.')
        if self.state == self.State.FINALIZED and not self.finalized_at:
            raise ValidationError('최종 결과는 arena_finalize 명령으로 확정하세요.')
        if previous and previous.state == self.State.FINALIZED and (
            self.state != previous.state or self.starts_at != previous.starts_at or self.ends_at != previous.ends_at
        ):
            raise ValidationError('확정된 대회는 다시 열거나 일정을 변경할 수 없습니다.')


class Participant(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    is_test = models.BooleanField(default=False, verbose_name='서버 검증용 참가자 (순위 제외)')
    selected_submission = models.ForeignKey(
        'Submission', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=['competition', 'user'], name='arena_member_unique')]

    @property
    def public_name(self):
        return self.user.username

    def __str__(self):
        return self.public_name


class DailyQuota(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    day = models.DateField()
    used = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['participant', 'day'], name='arena_quota_unique')]


class Submission(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', '채점 대기'
        SCORING = 'scoring', '채점 중'
        SCORED = 'scored', '채점 완료'
        ERROR = 'error', '채점 지연 · 복구 필요'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name='submissions')
    dataset = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    request_key = models.UUIDField()
    content_hash = models.CharField(max_length=64)
    filename = models.CharField(max_length=160)
    accepted_at = models.DateTimeField()
    quota_day = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    public_rmse = models.FloatField(null=True, editable=False)
    private_rmse = models.FloatField(null=True, editable=False)
    worker_token = models.UUIDField(null=True, editable=False)
    lease_until = models.DateTimeField(null=True, editable=False)
    attempts = models.PositiveSmallIntegerField(default=0, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['participant', 'request_key'], name='arena_request_unique')]
        indexes = [models.Index(fields=['status', 'accepted_at'])]
        ordering = ['-accepted_at', '-id']


class FinalResult(models.Model):
    participant = models.OneToOneField(Participant, on_delete=models.PROTECT)
    submission = models.OneToOneField(Submission, on_delete=models.PROTECT)
    rank = models.PositiveIntegerField(unique=True)
    public_name = models.CharField(max_length=150)
    private_rmse = models.FloatField()
    selection_reason = models.CharField(max_length=12, choices=[('manual', '본인 선택'), ('automatic', '자동 선택')])

    class Meta:
        ordering = ['rank']
