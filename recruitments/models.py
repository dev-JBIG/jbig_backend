from django.db import models
from django.conf import settings
from django.utils import timezone


class Recruitment(models.Model):
    class RecruitmentType(models.IntegerChoices):
        STUDY = 1, '스터디'
        COMPETITION = 2, '경진대회'
        PROJECT = 3, '프로젝트'
        OTHER = 4, '기타'

    class Status(models.IntegerChoices):
        OPEN = 1, '모집중'
        CLOSED = 2, '모집마감'
        COMPLETED = 3, '완료'
        CANCELLED = 4, '취소됨'

    post = models.OneToOneField(
        'boards.Post',
        on_delete=models.CASCADE,
        related_name='recruitment',
        primary_key=True,
        verbose_name='게시글'
    )
    recruitment_type = models.IntegerField(
        choices=RecruitmentType.choices,
        verbose_name='모집 유형'
    )
    status = models.IntegerField(
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        verbose_name='모집 상태'
    )
    max_members = models.PositiveIntegerField(
        default=0,
        verbose_name='모집 인원',
        help_text='0이면 인원 제한 없음'
    )
    deadline = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='모집 마감일',
        help_text='null이면 상시모집'
    )
    required_skills = models.JSONField(
        default=list,
        blank=True,
        verbose_name='필요 기술/조건'
    )
    contact_info = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='연락처',
        help_text='수락된 지원자에게만 공개'
    )
    show_applicants = models.BooleanField(
        default=False,
        verbose_name='지원자 공개',
        help_text='True이면 지원자끼리 서로의 이름·기수를 볼 수 있음'
    )
    accepted_count = models.PositiveIntegerField(
        default=0,
        verbose_name='합류 확정 수'
    )

    class Meta:
        db_table = 'recruitment'
        verbose_name = '모집'
        verbose_name_plural = '모집 목록'

    def __str__(self):
        return f'[{self.get_recruitment_type_display()}] {self.post.title}'

    def check_and_close_if_expired(self):
        """마감일이 지났으면 자동으로 CLOSED 상태로 전환 (lazy check)"""
        if self.status == self.Status.OPEN and self.deadline and self.deadline < timezone.now():
            self.status = self.Status.CLOSED
            self.save(update_fields=['status'])
            return True
        return False


class Application(models.Model):
    class Status(models.IntegerChoices):
        PENDING = 1, '대기중'
        ACCEPTED = 2, '수락됨'
        REJECTED = 3, '거절됨'

    recruitment = models.ForeignKey(
        Recruitment,
        on_delete=models.CASCADE,
        related_name='applications',
        verbose_name='모집'
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='applications',
        verbose_name='지원자'
    )
    status = models.IntegerField(
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name='지원 상태'
    )
    message = models.TextField(
        blank=True,
        verbose_name='지원 메시지'
    )
    recruiter_note = models.TextField(
        blank=True,
        verbose_name='모집자 메모',
        help_text='모집자만 볼 수 있는 내부 메모'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'application'
        verbose_name = '지원'
        verbose_name_plural = '지원 목록'
        unique_together = ('recruitment', 'applicant')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.applicant} -> {self.recruitment.post.title} ({self.get_status_display()})'
