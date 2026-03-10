from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from boards.models import Notification, Post
from boards.views import create_notification

from .models import Recruitment, Application
from .serializers import (
    RecruitmentDetailSerializer,
    RecruitmentListSerializer,
    RecruitmentCreateSerializer,
    ApplicationCreateSerializer,
    ApplicationFullSerializer,
    ApplicationPublicSerializer,
    ApplicationOwnSerializer,
    MyApplicationSerializer,
)


class RecruitmentListAPIView(generics.ListAPIView):
    """모집 목록 조회 (필터: status, type, board_id)"""
    serializer_class = RecruitmentListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Recruitment.objects.select_related('post', 'post__author', 'post__board')

        # Lazy deadline check — 만료된 모집 자동 마감
        expired = qs.filter(
            status=Recruitment.Status.OPEN,
            deadline__lt=timezone.now(),
            deadline__isnull=False
        )
        if expired.exists():
            expired.update(status=Recruitment.Status.CLOSED)

        s = self.request.query_params.get('status')
        rtype = self.request.query_params.get('type')
        board_id = self.request.query_params.get('board_id')

        if s:
            qs = qs.filter(status=s)
        if rtype:
            qs = qs.filter(recruitment_type=rtype)
        if board_id:
            qs = qs.filter(post__board_id=board_id)

        return qs.order_by('-post__created_at')


class RecruitmentDetailAPIView(APIView):
    """모집 상세 조회"""
    permission_classes = [AllowAny]

    def get(self, request, post_id):
        recruitment = get_object_or_404(
            Recruitment.objects.select_related('post', 'post__author'),
            post_id=post_id
        )
        recruitment.check_and_close_if_expired()
        serializer = RecruitmentDetailSerializer(recruitment, context={'request': request})
        return Response(serializer.data)

    def patch(self, request, post_id):
        """모집 정보 수정 (모집자/관리자)"""
        recruitment = get_object_or_404(Recruitment, post_id=post_id)
        if recruitment.post.author != request.user and not request.user.is_staff:
            return Response({'error': '권한이 없습니다.'}, status=status.HTTP_403_FORBIDDEN)

        # max_members 변경 시 accepted_count 검증
        new_max = request.data.get('max_members')
        if new_max is not None and int(new_max) > 0 and int(new_max) < recruitment.accepted_count:
            return Response(
                {'error': f'이미 수락된 인원({recruitment.accepted_count}명)보다 적은 수로 변경할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = RecruitmentCreateSerializer(recruitment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(RecruitmentDetailSerializer(recruitment, context={'request': request}).data)


class RecruitmentStatusAPIView(APIView):
    """모집 상태 변경 (close, reopen, complete, cancel)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id, action):
        recruitment = get_object_or_404(
            Recruitment.objects.select_related('post', 'post__author'),
            post_id=post_id
        )
        if recruitment.post.author != request.user and not request.user.is_staff:
            return Response({'error': '권한이 없습니다.'}, status=status.HTTP_403_FORBIDDEN)

        if action == 'close':
            if recruitment.status != Recruitment.Status.OPEN:
                return Response({'error': '모집중 상태에서만 마감할 수 있습니다.'}, status=status.HTTP_400_BAD_REQUEST)
            recruitment.status = Recruitment.Status.CLOSED
            recruitment.save(update_fields=['status'])
            # 대기중인 지원자에게 알림
            self._notify_pending_closed(recruitment, request.user)

        elif action == 'reopen':
            if recruitment.status != Recruitment.Status.CLOSED:
                return Response({'error': '마감 상태에서만 재오픈할 수 있습니다.'}, status=status.HTTP_400_BAD_REQUEST)
            if recruitment.max_members > 0 and recruitment.accepted_count >= recruitment.max_members:
                return Response({'error': '모집 인원이 가득 차 재오픈할 수 없습니다.'}, status=status.HTTP_400_BAD_REQUEST)
            recruitment.status = Recruitment.Status.OPEN
            recruitment.save(update_fields=['status'])

        elif action == 'complete':
            if recruitment.status not in (Recruitment.Status.OPEN, Recruitment.Status.CLOSED):
                return Response({'error': '완료 처리할 수 없는 상태입니다.'}, status=status.HTTP_400_BAD_REQUEST)
            recruitment.status = Recruitment.Status.COMPLETED
            recruitment.save(update_fields=['status'])

        elif action == 'cancel':
            if recruitment.status in (Recruitment.Status.COMPLETED, Recruitment.Status.CANCELLED):
                return Response({'error': '이미 종료된 모집입니다.'}, status=status.HTTP_400_BAD_REQUEST)
            recruitment.status = Recruitment.Status.CANCELLED
            recruitment.save(update_fields=['status'])
            # 대기중인 지원자에게 알림
            self._notify_pending_closed(recruitment, request.user)

        else:
            return Response({'error': '잘못된 액션입니다.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(RecruitmentDetailSerializer(recruitment, context={'request': request}).data)

    def _notify_pending_closed(self, recruitment, actor):
        pending = recruitment.applications.filter(status=Application.Status.PENDING)
        notifications = [
            Notification(
                recipient=app.applicant,
                actor=actor,
                notification_type=Notification.NotificationType.RECRUITMENT_CLOSED,
                post=recruitment.post
            )
            for app in pending if app.applicant != actor
        ]
        if notifications:
            Notification.objects.bulk_create(notifications)


class ApplyAPIView(APIView):
    """모집에 지원"""
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        recruitment = get_object_or_404(
            Recruitment.objects.select_related('post', 'post__author'),
            post_id=post_id
        )
        recruitment.check_and_close_if_expired()

        if recruitment.post.author == request.user:
            return Response({'error': '자신의 모집에는 지원할 수 없습니다.'}, status=status.HTTP_400_BAD_REQUEST)

        if recruitment.status != Recruitment.Status.OPEN:
            return Response({'error': '모집이 마감되었습니다.'}, status=status.HTTP_400_BAD_REQUEST)

        if recruitment.max_members > 0 and recruitment.accepted_count >= recruitment.max_members:
            return Response({'error': '모집 인원이 가득 찼습니다.'}, status=status.HTTP_400_BAD_REQUEST)

        if Application.objects.filter(recruitment=recruitment, applicant=request.user).exists():
            return Response({'error': '이미 지원한 모집입니다.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        app = Application.objects.create(
            recruitment=recruitment,
            applicant=request.user,
            message=serializer.validated_data.get('message', '')
        )

        # 모집자에게 알림
        create_notification(
            recipient=recruitment.post.author,
            actor=request.user,
            notification_type=Notification.NotificationType.APPLICATION_RECEIVED,
            post=recruitment.post
        )

        return Response(ApplicationOwnSerializer(app).data, status=status.HTTP_201_CREATED)


class MyApplicationAPIView(APIView):
    """내 지원 상태 조회 / 철회"""
    permission_classes = [IsAuthenticated]

    def get(self, request, post_id):
        recruitment = get_object_or_404(Recruitment, post_id=post_id)
        app = Application.objects.filter(recruitment=recruitment, applicant=request.user).first()
        if not app:
            return Response({'detail': '지원 내역이 없습니다.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ApplicationOwnSerializer(app).data)

    def delete(self, request, post_id):
        """지원 철회 (레코드 삭제 — 재지원 가능)"""
        recruitment = get_object_or_404(Recruitment, post_id=post_id)
        app = Application.objects.filter(recruitment=recruitment, applicant=request.user).first()
        if not app:
            return Response({'detail': '지원 내역이 없습니다.'}, status=status.HTTP_404_NOT_FOUND)
        app.delete()  # signal이 accepted_count 조정
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApplicationListAPIView(generics.ListAPIView):
    """지원자 목록 (권한별 다른 시리얼라이저)"""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        recruitment = get_object_or_404(
            Recruitment.objects.select_related('post', 'post__author'),
            post_id=self.kwargs['post_id']
        )
        user = self.request.user
        is_owner = (recruitment.post.author == user or user.is_staff)

        if is_owner:
            return recruitment.applications.select_related('applicant').all()

        # show_applicants이고 본인이 지원자인 경우
        if recruitment.show_applicants and recruitment.applications.filter(applicant=user).exists():
            return recruitment.applications.select_related('applicant').all()

        # 본인 것만
        return recruitment.applications.filter(applicant=user).select_related('applicant')

    def get_serializer_class(self):
        recruitment = get_object_or_404(
            Recruitment.objects.select_related('post', 'post__author'),
            post_id=self.kwargs['post_id']
        )
        user = self.request.user
        is_owner = (recruitment.post.author == user or user.is_staff)

        if is_owner:
            return ApplicationFullSerializer
        if recruitment.show_applicants and recruitment.applications.filter(applicant=user).exists():
            return ApplicationPublicSerializer
        return ApplicationOwnSerializer


class AcceptRejectApplicationAPIView(APIView):
    """지원 수락/거절"""
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id, app_id, action):
        recruitment = get_object_or_404(
            Recruitment.objects.select_related('post', 'post__author'),
            post_id=post_id
        )
        if recruitment.post.author != request.user and not request.user.is_staff:
            return Response({'error': '권한이 없습니다.'}, status=status.HTTP_403_FORBIDDEN)

        app = get_object_or_404(Application, id=app_id, recruitment=recruitment)

        if app.status != Application.Status.PENDING:
            return Response({'error': '대기중인 지원만 수락/거절할 수 있습니다.'}, status=status.HTTP_400_BAD_REQUEST)

        # recruiter_note 업데이트
        note = request.data.get('recruiter_note')
        if note is not None:
            app.recruiter_note = note

        if action == 'accept':
            if recruitment.max_members > 0 and recruitment.accepted_count >= recruitment.max_members:
                return Response({'error': '모집 인원이 가득 찼습니다.'}, status=status.HTTP_400_BAD_REQUEST)

            app.status = Application.Status.ACCEPTED
            app.save(update_fields=['status', 'recruiter_note', 'updated_at'])

            # accepted_count 증가
            Recruitment.objects.filter(pk=recruitment.pk).update(accepted_count=F('accepted_count') + 1)
            recruitment.refresh_from_db()

            # 인원 충족 시 자동 마감
            if recruitment.max_members > 0 and recruitment.accepted_count >= recruitment.max_members:
                recruitment.status = Recruitment.Status.CLOSED
                recruitment.save(update_fields=['status'])

            # 지원자에게 수락 알림
            create_notification(
                recipient=app.applicant,
                actor=request.user,
                notification_type=Notification.NotificationType.APPLICATION_ACCEPTED,
                post=recruitment.post
            )

        elif action == 'reject':
            app.status = Application.Status.REJECTED
            app.save(update_fields=['status', 'recruiter_note', 'updated_at'])

            # 지원자에게 거절 알림
            create_notification(
                recipient=app.applicant,
                actor=request.user,
                notification_type=Notification.NotificationType.APPLICATION_REJECTED,
                post=recruitment.post
            )
        else:
            return Response({'error': '잘못된 액션입니다.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ApplicationFullSerializer(app).data)


class MyRecruitmentsAPIView(generics.ListAPIView):
    """내가 만든 모집 목록"""
    serializer_class = RecruitmentListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Recruitment.objects.filter(
            post__author=self.request.user
        ).select_related('post', 'post__board').order_by('-post__created_at')


class MyApplicationsAPIView(generics.ListAPIView):
    """내가 지원한 목록"""
    serializer_class = MyApplicationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Application.objects.filter(
            applicant=self.request.user
        ).select_related(
            'recruitment', 'recruitment__post', 'recruitment__post__board'
        ).order_by('-created_at')
