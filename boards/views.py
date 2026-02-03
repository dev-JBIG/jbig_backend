import os
import re
import uuid
import logging
from datetime import datetime

import boto3
import requests
from botocore.client import Config
from botocore.exceptions import ClientError

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.db.models import F, Q, Value, CharField, Func

from rest_framework import generics, status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample, OpenApiParameter

logger = logging.getLogger(__name__)

from .models import Board, Post, Comment, Category, Notification, Draft
from .serializers import (
    BoardSerializer, PostListSerializer, PostDetailSerializer, PostCreateUpdateSerializer,
    CommentSerializer, CategoryListResponseSerializer, PostListResponseSerializer, NotificationSerializer,
    DraftSerializer
)
from .permissions import (
    IsOwnerOrReadOnly,
    IsBoardReadable,
    IsPostWritable,
    IsCommentWritable,
    PostDetailPermission
)

# Cloudflare Turnstile 검증 함수
def verify_turnstile(token: str, ip: str) -> bool:
    """Cloudflare Turnstile 토큰 검증"""
    if not settings.TURNSTILE_SECRET_KEY:
        return True  # 개발 환경에서는 검증 건너뛰기

    try:
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={
                'secret': settings.TURNSTILE_SECRET_KEY,
                'response': token,
                'remoteip': ip,
            },
            timeout=10
        )
        result = response.json()
        return result.get('success', False)
    except Exception as e:
        logger.error(f"Turnstile 검증 실패: {e}")
        return False


# 데코레이터가 뷰로 착각해서;; 맨 위로 뺌
class RegexpReplace(Func):
    function = 'REGEXP_REPLACE'
    template = "%(function)s(%(expressions)s, '%(pattern)s', '%(replacement)s', 'g')"

    def __init__(self, expression, pattern, replacement='', **extra):
        super().__init__(
            expression,
            pattern=pattern,
            replacement=replacement,
            output_field=CharField(),
            **extra
        )
        
@extend_schema(
    tags=['게시판'],
    summary="게시글 좋아요/취소",
    description="특정 게시글에 좋아요를 추가하거나 취소합니다. 이미 좋아요를 누른 상태에서 요청하면 좋아요가 취소됩니다.",
    responses={
        200: {
            'description': '좋아요 상태 변경 성공',
            'examples': {
                '좋아요 추가': {
                    'value': {'likes_count': 28, 'is_liked': True}
                },
                '좋아요 취소': {
                    'value': {'likes_count': 27, 'is_liked': False}
                }
            }
        }
    }
)
class PostLikeAPIView(generics.GenericAPIView):
    queryset = Post.objects.all()
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = 'post_id'

    def post(self, request, *args, **kwargs):
        post = self.get_object()
        user = request.user

        try:
            like = post.likes.through.objects.get(user=user, post=post)
            like.delete()
            is_liked = False
        except post.likes.through.DoesNotExist:
            post.likes.add(user)
            is_liked = True
            # 좋아요 추가 시에만 알림 생성
            create_notification(
                recipient=post.author,
                actor=user,
                notification_type=Notification.NotificationType.LIKE,
                post=post
            )

        likes_count = post.likes.count()
        return Response({'likes_count': likes_count, 'is_liked': is_liked}, status=status.HTTP_200_OK)


@extend_schema(
    tags=['댓글'],
    summary="댓글 좋아요/취소",
    description="특정 댓글에 좋아요를 추가하거나 취소합니다. 이미 좋아요를 누른 상태에서 요청하면 좋아요가 취소됩니다. 좋아요 추가 시 댓글 작성자에게 알림이 전송됩니다.",
    responses={
        200: {
            'description': '좋아요 상태 변경 성공',
            'examples': {
                '좋아요 추가': {
                    'value': {'likes': 5, 'isLiked': True}
                },
                '좋아요 취소': {
                    'value': {'likes': 4, 'isLiked': False}
                }
            }
        }
    }
)
class CommentLikeAPIView(generics.GenericAPIView):
    queryset = Comment.objects.all()
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = 'comment_id'

    def post(self, request, *args, **kwargs):
        comment = self.get_object()
        user = request.user

        try:
            like = comment.likes.through.objects.get(user=user, comment=comment)
            like.delete()
            is_liked = False
        except comment.likes.through.DoesNotExist:
            comment.likes.add(user)
            is_liked = True
            # 댓글 좋아요 추가 시에만 알림 생성 (비회원 댓글 제외)
            if comment.author:
                create_notification(
                    recipient=comment.author,
                    actor=user,
                    notification_type=Notification.NotificationType.COMMENT_LIKE,
                    post=comment.post,
                    comment=comment
                )

        likes_count = comment.likes.count()
        return Response({'likes': likes_count, 'isLiked': is_liked}, status=status.HTTP_200_OK)


@extend_schema(
    tags=['게시글'],
    summary="게시글 검색",
    description="제목, 내용, 작성자명을 기준으로 게시글을 검색합니다. 사용자의 권한에 따라 접근 가능한 게시글 내에서만 검색이 수행됩니다.",
    parameters=[
        OpenApiParameter(
            name='q',
            description='검색할 키워드',
            required=True,
            type=str,
            location=OpenApiParameter.QUERY
        ),
    ]
)


class PostSearchView(generics.ListAPIView):
    serializer_class = PostListSerializer

    def get_queryset(self):
        query = self.request.query_params.get('q', None)
        if not query:
            return Post.objects.none()

        board_id = self.kwargs.get('board_id', None)
        user = self.request.user

        if board_id:
            board = get_object_or_404(Board, id=board_id)
            if board.read_permission == 'staff' and not (user.is_authenticated and user.is_staff):
                return Post.objects.none()
            base_queryset = Post.objects.filter(board_id=board_id)
        else:
            base_queryset = Post.objects.all()
            if not (user.is_authenticated and user.is_staff):
                base_queryset = base_queryset.filter(board__read_permission='all')

        queryset = base_queryset.visible_for_user(user)

        # URL/링크를 제거하는 정규식 패턴
        url_pattern = r'!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)|https?://[^\s]+|www\.[^\s]+'
        
        # content_md에서 URL 제거 후 검색
        queryset = queryset.annotate(
            clean_content=RegexpReplace('content_md', url_pattern, '')
        )

        # 부분 검색되게 수정
        search_filter = (
            Q(title__icontains=query) |
            Q(clean_content__icontains=query) |
            Q(author__username__icontains=query)
        )

        queryset = queryset.filter(search_filter).distinct().order_by('-created_at')
        return queryset

@extend_schema(
    tags=['게시글'],
    summary="전체 게시글 검색",
    description="모든 게시판의 게시글을 대상으로 검색합니다. 사용자의 권한에 따라 접근 가능한 게시글 내에서만 검색이 수행됩니다.",
    parameters=[
        OpenApiParameter(
            name='q',
            description='검색할 키워드',
            required=True,
            type=str,
            location=OpenApiParameter.QUERY
        ),
    ]
)
class AllPostSearchView(PostSearchView):
    def get_queryset(self):
        self.kwargs['board_id'] = None
        return super().get_queryset()


@extend_schema(tags=['게시판'])
@extend_schema_view(
    list=extend_schema(
        summary="카테고리별 게시판 목록 조회",
        description="모든 카테고리와 해당 카테고리에 속한 게시판 목록을 조회합니다. 응답의 최상단에는 전체 게시글의 수가 포함됩니다.",
        responses={200: CategoryListResponseSerializer},
    )
)
class BoardListViewSet(viewsets.ViewSet):
    def list(self, request, *args, **kwargs):
        total_post_count = Post.objects.count()
        categories = Category.objects.prefetch_related('boards').all()
        response_payload = {
            "total_post_count": total_post_count,
            "categories": categories
        }
        serializer = CategoryListResponseSerializer(response_payload)
        return Response(serializer.data)

@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="전체 게시판 목록 조회",
        description="사이트의 모든 게시판 목록을 조회합니다.",
    )
)
class BoardListAPIView(generics.ListAPIView):
    serializer_class = BoardSerializer
    
    def get_queryset(self):
        return Board.objects.all()


@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 목록 조회",
        description="""특정 게시판의 정보 및 게시글 목록을 조회합니다.\n- **게시판 접근 권한**: 게시판의 `read_permission` 설정에 따라 접근이 제어됩니다.\n- **게시글 필터링**: 사용자의 권한(스태프, 인증 여부)에 따라 조회되는 게시글이 자동으로 필터링됩니다. (예: 스태프 전용 글, 본인 작성 해명글 등) """,
        responses={
            200: OpenApiResponse(
                response=PostListResponseSerializer,
                examples=[
                    OpenApiExample(
                        'Success',
                        summary='게시글 목록 조회 성공',
                        value={
                            "board": {
                                "id": 1,
                                "name": "자유게시판",
                                "category": {"id": 1, "name": "커뮤니티"},
                                "read_permission": True,
                                "post_permission": True,
                                "comment_permission": True
                            },
                            "count": 1,
                            "next": None,
                            "previous": None,
                            "results": [
                                {
                                    "id": 101,
                                    "board_post_id": 1,
                                    "title": "첫 번째 게시글입니다.",
                                    "user_id": "testuser",
                                    "author": "테스트유저",
                                    "author_semester": 1,
                                    "created_at": "2025-09-17T12:30:00Z",
                                    "views": 150,
                                    "likes_count": 10,
                                    "attachments": [
                                        {"id": 1, "file": "/media/attachments/file1.pdf", "filename": "file1.pdf"}
                                    ]
                                }
                            ]
                        }
                    )
                ]
            ),
            403: OpenApiResponse(description="게시판에 대한 읽기 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시판입니다."),
        },
    ),
    post=extend_schema(
        summary="게시글 생성",
        description="""특정 게시판에 새로운 게시글을 작성합니다.\n- **권한 (Board Level)**: 게시판의 `post_permission` 설정에 따라 접근이 제어됩니다.\n  - `all`: 인증된 사용자 누구나 작성 가능\n  - `staff`: 스태프만 작성 가능""",
        request=PostCreateUpdateSerializer,
        examples=[
            OpenApiExample(
                '게시글 생성 요청',
                summary='새로운 게시글을 작성하는 예시입니다.',
                value={
                    "title": "새로운 게시글 제목",
                    "content_md": "# 제목\n\n여기에 게시글 내용이 마크다운 형식으로 들어갑니다.\n\n- 목록1\n- 목록2",
                    "attachment_paths": [
                        {"url": "http://example.com/media/attachments/file1.pdf", "name": "file1.pdf"},
                        {"url": "http://example.com/media/attachments/file2.jpg", "name": "file2.jpg"}
                    ],
                    "post_type": 1
                }
            )
        ],
        responses={
            201: PostListSerializer,
            400: OpenApiResponse(description="잘못된 요청 데이터입니다."),
            403: OpenApiResponse(description="게시판에 대한 쓰기 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시판입니다."),
        },
    )
)
class PostListCreateAPIView(generics.ListCreateAPIView):
    lookup_url_kwarg = 'board_id'

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsBoardReadable()]
        elif self.request.method == 'POST':
            return [IsPostWritable()]
        return [AllowAny()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PostCreateUpdateSerializer
        return PostListSerializer

    def get_queryset(self):
        board_id = self.kwargs.get('board_id')
        return Post.objects.filter(board_id=board_id).visible_for_user(self.request.user).order_by('-created_at')

    def get_object(self):
        board_id = self.kwargs.get(self.lookup_url_kwarg)
        obj = get_object_or_404(Board, pk=board_id)
        # self.check_object_permissions(self.request, obj) # This line causes recursion
        return obj

    def list(self, request, *args, **kwargs):
        board = self.get_object()
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            response_data = {
                'board': BoardSerializer(board, context={'request': request}).data,
                'count': paginated_response.data['count'],
                'next': paginated_response.data['next'],
                'previous': paginated_response.data['previous'],
                'results': paginated_response.data['results']
            }
            return Response(response_data)

        serializer = self.get_serializer(queryset, many=True)
        response_data = {
            'board': BoardSerializer(board, context={'request': request}).data,
            'results': serializer.data
        }
        return Response(response_data)

    def perform_create(self, serializer):
        board = get_object_or_404(Board, pk=self.kwargs.get('board_id'))
        self.check_object_permissions(self.request, board)
        
        post_type = Post.PostType.DEFAULT # Default to DEFAULT
        if board.board_type == Board.BoardType.JUSTIFICATION_LETTER:
            post_type = Post.PostType.JUSTIFICATION_LETTER
        
        is_anonymous = serializer.validated_data.get('is_anonymous', True)
        serializer.save(author=self.request.user, board=board, post_type=post_type, is_anonymous=is_anonymous)

@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 상세 조회",
        description=(
            "게시글의 상세 정보를 조회합니다.\n"
            "- 권한 (Board Level): 먼저 게시판의 `read_permission`을 확인합니다.\n"
            "- 권한 (Post Level): 게시글의 `post_type`에 따라 상세 조회 권한이 결정됩니다.\n"
            "  - DEFAULT(일반): 게시판 읽기 권한이 있으면 누구나 조회 가능\n"
            "  - STAFF_ONLY(스태프 전용): 스태프만 조회 가능\n"
            "  - JUSTIFICATION_LETTER(해명글): 작성자 또는 스태프만 조회 가능\n"
            "- 조회수 증가: 이 API를 호출하면 해당 게시글의 조회수가 1 증가합니다."
        ),
        responses={
            200: PostDetailSerializer,
            403: OpenApiResponse(description="게시글을 읽을 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시글입니다."),
        },
    ),
    put=extend_schema(summary="게시글 수정", description="작성자 또는 스태프만 게시글을 수정할 수 있습니다."),
    patch=extend_schema(summary="게시글 부분 수정", description="작성자 또는 스태프만 게시글을 부분 수정할 수 있습니다."),
    delete=extend_schema(summary="게시글 삭제", description="작성자 또는 스태프만 게시글을 삭제할 수 있습니다.")
)
class PostRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Post.objects.all()
    permission_classes = [IsBoardReadable, PostDetailPermission]
    lookup_url_kwarg = 'post_id'

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return PostCreateUpdateSerializer
        return PostDetailSerializer  

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.views += 1
        instance.save(update_fields=['views'])

        serializer = self.get_serializer(instance, context={'request': request})
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """게시글 수정 시 제거된 파일들을 NCP에서 삭제"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        # 게시판 변경 권한 검증
        board_id = request.data.get('board_id')
        if board_id is not None:
            from .models import Board
            new_board = Board.objects.filter(id=board_id).first()
            if new_board and new_board.post_permission == 'staff' and not request.user.is_staff:
                return Response(
                    {"detail": "해당 게시판에는 글을 작성할 권한이 없습니다."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 수정 전 파일 키 수집
        old_attachment_keys = set()
        if instance.attachment_paths and isinstance(instance.attachment_paths, list):
            for att in instance.attachment_paths:
                if isinstance(att, dict) and 'path' in att:
                    file_key = att['path']
                    if file_key.startswith('uploads/'):
                        old_attachment_keys.add(file_key)

        old_content_keys = set()
        if instance.content_md:
            old_content_keys = set(re.findall(r'ncp-key://(uploads/[^\s\)]+)', instance.content_md))

        # 실제 수정 수행
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # 수정 후 파일 키 수집
        instance.refresh_from_db()
        new_attachment_keys = set()
        if instance.attachment_paths and isinstance(instance.attachment_paths, list):
            for att in instance.attachment_paths:
                if isinstance(att, dict) and 'path' in att:
                    file_key = att['path']
                    if file_key.startswith('uploads/'):
                        new_attachment_keys.add(file_key)

        new_content_keys = set()
        if instance.content_md:
            new_content_keys = set(re.findall(r'ncp-key://(uploads/[^\s\)]+)', instance.content_md))

        # 삭제할 파일 키 계산 (기존에 있었지만 새로운 버전에 없는 것)
        keys_to_delete = (old_attachment_keys - new_attachment_keys) | (old_content_keys - new_content_keys)

        # NCP에서 삭제된 파일 제거
        if keys_to_delete:
            try:
                s3_client = boto3.client(
                    's3',
                    endpoint_url=settings.NCP_ENDPOINT_URL,
                    aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.NCP_SECRET_KEY,
                    config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
                )

                for key in keys_to_delete:
                    try:
                        s3_client.delete_object(Bucket=settings.NCP_BUCKET_NAME, Key=key)
                        logger.info(f"NCP 파일 삭제 완료 (수정 시 제거됨): {key}")
                    except ClientError as e:
                        logger.error(f"NCP 파일 삭제 실패 (Key: {key}): {e}")
            except Exception as e:
                logger.error(f"S3 클라이언트 생성 실패: {e}")

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """게시글 삭제 시 NCP에 저장된 파일들도 함께 삭제"""
        instance = self.get_object()

        # 삭제할 파일 키 수집
        keys_to_delete = []

        # 1. attachment_paths에서 파일 키 수집
        if instance.attachment_paths and isinstance(instance.attachment_paths, list):
            for att in instance.attachment_paths:
                if isinstance(att, dict) and 'path' in att:
                    file_key = att['path']
                    if file_key.startswith('uploads/'):
                        keys_to_delete.append(file_key)

        # 2. content_md에서 ncp-key:// 이미지 키 수집
        if instance.content_md:
            ncp_keys = re.findall(r'ncp-key://(uploads/[^\s\)]+)', instance.content_md)
            keys_to_delete.extend(ncp_keys)

        # 3. NCP에서 파일 삭제
        if keys_to_delete:
            try:
                s3_client = boto3.client(
                    's3',
                    endpoint_url=settings.NCP_ENDPOINT_URL,
                    aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.NCP_SECRET_KEY,
                    config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
                )

                for key in keys_to_delete:
                    try:
                        s3_client.delete_object(Bucket=settings.NCP_BUCKET_NAME, Key=key)
                        logger.info(f"NCP 파일 삭제 완료: {key}")
                    except ClientError as e:
                        logger.error(f"NCP 파일 삭제 실패 (Key: {key}): {e}")
            except Exception as e:
                logger.error(f"S3 클라이언트 생성 실패: {e}")

        # 4. DB에서 게시글 삭제
        return super().destroy(request, *args, **kwargs)

@extend_schema(tags=['댓글'])
@extend_schema_view(
    get=extend_schema(summary="댓글 목록 조회"),
    post=extend_schema(
        summary="댓글 생성",
        description="""특정 게시글에 새로운 댓글을 작성합니다.\n- **권한 (Board Level)**: 게시판의 `comment_permission` 설정에 따라 접근이 제어됩니다.\n  - `all`: 비회원 포함 누구나 작성 가능\n  - `staff`: 스태프만 작성 가능\n- **비회원 댓글**: 비회원은 자동으로 IP 기반 익명 닉네임이 부여됩니다.\n- **회원 익명 작성**: 회원은 `is_anonymous` 필드를 true로 설정하면 익명으로 작성됩니다 (기본값: true).""",
    )
)
class CommentListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsCommentWritable()]
        return [AllowAny()]

    def get_queryset(self):
        post_id = self.kwargs.get('post_id')
        return Comment.objects.filter(post_id=post_id, parent__isnull=True).order_by('created_at')

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        post = get_object_or_404(Post, pk=self.kwargs.get('post_id'))
        is_anonymous = serializer.validated_data.get('is_anonymous', True)

        # 비회원인 경우 author=None으로 저장
        if self.request.user.is_authenticated:
            comment = serializer.save(author=self.request.user, post=post, is_anonymous=is_anonymous)

            # 알림 생성 (회원만)
            if comment.parent and comment.parent.author:
                # 대댓글인 경우: 부모 댓글 작성자에게 알림
                create_notification(
                    recipient=comment.parent.author,
                    actor=self.request.user,
                    notification_type=Notification.NotificationType.REPLY,
                    post=post,
                    comment=comment
                )
            elif post.author:
                # 일반 댓글인 경우: 게시글 작성자에게 알림
                create_notification(
                    recipient=post.author,
                    actor=self.request.user,
                    notification_type=Notification.NotificationType.COMMENT,
                    post=post,
                    comment=comment
                )
        else:
            # 비회원 댓글 - IP 주소 추출
            x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0]
            else:
                ip = self.request.META.get('REMOTE_ADDR')

            # Turnstile CAPTCHA 검증
            turnstile_token = self.request.data.get('turnstile_token')
            if not verify_turnstile(turnstile_token, ip):
                raise ValidationError({'detail': 'CAPTCHA 검증에 실패했습니다. 다시 시도해주세요.'})

            comment = serializer.save(author=None, post=post, is_anonymous=is_anonymous, guest_id=ip)

            # 비회원 댓글 알림 (글 작성자에게)
            if post.author:
                create_notification(
                    recipient=post.author,
                    actor=None,  # 비회원이므로 actor 없음
                    notification_type=Notification.NotificationType.COMMENT,
                    post=post,
                    comment=comment
                )

@extend_schema(tags=['댓글'])
@extend_schema_view(
    put=extend_schema(summary="댓글 수정", description="작성자 또는 스태프만 댓글을 수정할 수 있습니다."),
    patch=extend_schema(summary="댓글 부분 수정", description="작성자 또는 스태프만 댓글을 부분 수정할 수 있습니다."),
    delete=extend_schema(summary="댓글 삭제", description="작성자 또는 스태프만 댓글을 삭제할 수 있습니다.")
)
class CommentUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsOwnerOrReadOnly]
    lookup_url_kwarg = 'comment_id'

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save()

@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="전체 게시글 목록 조회",
        description="모든 게시판의 게시글 목록을 조회합니다. 사용자의 권한에 따라 접근 가능한 게시판 및 게시글만 필터링되어 보여집니다.",
    )
)
class AllPostListAPIView(generics.ListAPIView):
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        user = self.request.user
        queryset = Post.objects.visible_for_user(user)
        
        if not (user.is_authenticated and user.is_staff):
            queryset = queryset.filter(board__read_permission='all')
                
        return queryset.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})



@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="게시판 상세 정보 조회",
        description="특정 게시판의 상세 정보를 조회합니다.",
    )
)
class BoardDetailAPIView(generics.RetrieveAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'board_id'
    permission_classes = [IsBoardReadable]



# 업로드 URL 발급해주는 GeneratePresignedURlAPIView 클래스

# 파일 업로드 제한 상수 (프론트엔드와 동일하게 유지)
BLOCKED_EXTENSIONS = {'jsp', 'php', 'asp', 'cgi', 'exe', 'sh', 'bat', 'cmd', 'ps1'}
MAX_EXTENSION_LENGTH = 10  # 확장자 최대 길이


@extend_schema(
    tags=['파일'],
    summary="업로드된 파일 삭제",
    description="NCP Object Storage에 업로드된 파일을 삭제합니다. 본인이 업로드한 파일만 삭제할 수 있습니다.",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'example': 'uploads/2025/01/01/12/uuid.png'}
            },
            'required': ['path']
        }
    },
    responses={
        200: OpenApiResponse(description="파일 삭제 성공"),
        400: OpenApiResponse(description="잘못된 파일 경로"),
        403: OpenApiResponse(description="본인이 업로드한 파일이 아닙니다"),
        404: OpenApiResponse(description="파일을 찾을 수 없습니다"),
    }
)
class DeleteFileAPIView(APIView):
    """업로드된 파일을 NCP에서 삭제하는 API"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        file_key = request.data.get('path')

        # 파일 경로 유효성 검사
        if not file_key or not isinstance(file_key, str):
            return Response({"error": "No file path provided."}, status=status.HTTP_400_BAD_REQUEST)

        file_key = file_key.strip()
        if not file_key.startswith('uploads/'):
            return Response({"error": "Invalid file path."}, status=status.HTTP_400_BAD_REQUEST)

        # 파일 경로에서 사용자 ID 추출하여 본인 파일인지 확인
        # 경로 형식: uploads/년/월/일/유저ID/uuid.확장자
        try:
            parts = file_key.split('/')
            if len(parts) >= 5:
                file_owner_id = int(parts[4])  # uploads/년/월/일/유저ID/...
                if file_owner_id != request.user.id:
                    return Response(
                        {"error": "You can only delete your own files."},
                        status=status.HTTP_403_FORBIDDEN
                    )
            else:
                return Response({"error": "Invalid file path format."}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, IndexError):
            return Response({"error": "Invalid file path format."}, status=status.HTTP_400_BAD_REQUEST)

        # NCP에서 파일 삭제
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.NCP_ENDPOINT_URL,
                aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                aws_secret_access_key=settings.NCP_SECRET_KEY,
                config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
            )

            # 파일 존재 여부 확인
            try:
                s3_client.head_object(Bucket=settings.NCP_BUCKET_NAME, Key=file_key)
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    return Response({"error": "File not found."}, status=status.HTTP_404_NOT_FOUND)
                raise

            # 파일 삭제
            s3_client.delete_object(Bucket=settings.NCP_BUCKET_NAME, Key=file_key)
            logger.info(f"NCP 파일 삭제 완료 (사용자 요청): {file_key}")

            return Response({"message": "File deleted successfully."}, status=status.HTTP_200_OK)

        except ClientError as e:
            logger.error(f"NCP 파일 삭제 실패 (Key: {file_key}): {e}")
            return Response({"error": "Failed to delete file."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"알 수 없는 에러: {e}")
            return Response({"error": "An unknown error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['파일'], # API 문서에서 '파일' 태그로 분류
    summary="파일 업로드용 Presigned URL 생성",
    description="NCP Object Storage에 파일을 직접 업로드할 수 있는 10분 만료 Presigned URL을 발급받습니다.",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'filename': {'type': 'string', 'example': 'example.png'}
            },
            'required': ['filename']
        }
    },
    responses={
        200: OpenApiResponse(
            description="URL 발급 성공",
            examples=[
                OpenApiExample(
                    'Success',
                    value={
                        "upload_url": "https://kr.object.ncloudstorage.com/jbig/uploads/2025/10/28/12/a1b2c3d4-....png?AWSAccessKeyId=...",
                        "file_key": "uploads/2025/10/28/12/a1b2c3d4-....png"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="파일 이름이 제공되지 않았거나 허용되지 않는 확장자입니다."),
        500: OpenApiResponse(description="URL 생성에 실패했습니다."),
    }
)
class GeneratePresignedURLAPIView(APIView):
    """
    파일 업로드를 위한 Presigned URL을 생성하는 API
    """
    permission_classes = [IsAuthenticated] # 로그인한 사용자만 이 API를 호출할 수 있음

    def post(self, request, *args, **kwargs):
        filename = request.data.get('filename')
        if not filename:
            return Response({"error": "No filename provided."}, status=status.HTTP_400_BAD_REQUEST)

        # 파일명 검증: 빈 문자열, 너무 긴 이름 체크
        filename = str(filename).strip()
        if not filename or len(filename) > 255:
            return Response({"error": "Invalid filename."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user

        # 1. 파일 확장자 추출 및 검증
        try:
            extension = os.path.splitext(filename)[1].lstrip('.').lower()
            if not extension:
                extension = 'bin'

            # 확장자 길이 검증
            if len(extension) > MAX_EXTENSION_LENGTH:
                return Response({"error": "Extension too long."}, status=status.HTTP_400_BAD_REQUEST)

            # 차단된 확장자 검증
            if extension in BLOCKED_EXTENSIONS:
                return Response(
                    {"error": f"File extension '.{extension}' is not allowed."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception:
            extension = 'bin'

        # 2. 서버에서 고유한 파일 경로(Key) 생성
        # uploads/년/월/일/유저ID/고유ID.확장자
        # 예: "uploads/2025/10/28/12/a1b2c3d4-e5f6-4a5b-8c7d-9e0f1a2b3c4d.png"
        # 주의: S3는 슬래시(/)만 사용하므로 os.path.join 대신 직접 조합
        now = datetime.now()
        file_key = f"uploads/{now:%Y}/{now:%m}/{now:%d}/{user.id}/{uuid.uuid4()}.{extension}"

        # 3. boto3 클라이언트 생성
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.NCP_ENDPOINT_URL,
                aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                aws_secret_access_key=settings.NCP_SECRET_KEY,
                config=Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'},
                    region_name=settings.NCP_REGION_NAME
                )
            )
        except Exception as e:
            logger.error(f"S3 클라이언트 생성 실패: {e}")
            return Response({"error": "S3 client creation failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 4. Presigned URL (업로드용) 생성
        try:
            # URL 만료 시간: 600초 (10분)
            upload_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.NCP_BUCKET_NAME,
                    'Key': file_key,
                    # 'ContentType': 'image/png' # 필요시 파일 타입 지정
                },
                ExpiresIn=600 
            )

            # [추가] 다운로드용 URL도 미리 생성 (1시간 만료)
            download_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.NCP_BUCKET_NAME,
                    'Key': file_key,
                },
                ExpiresIn=3600  # 1시간
            )

            # Public URL 생성 (영구적, 팝업 이미지 등에 사용)
            # NCP Object Storage의 public URL 형식: {endpoint}/{bucket}/{file-key}
            public_url = f"{settings.NCP_ENDPOINT_URL}/{settings.NCP_BUCKET_NAME}/{file_key}"

            # React에게 업로드할 URL과 DB에 저장할 Key를 함께 전달
            return Response({
                "upload_url": upload_url,
                "file_key": file_key,
                "download_url": download_url,
                "url": public_url  # 영구적인 public URL 추가
            }, status=status.HTTP_200_OK)

        except ClientError as e:
            logger.error(f"Presigned URL 생성 실패: {e}")
            return Response({"error": "Failed to generate presigned URL."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"알 수 없는 에러: {e}")
            return Response({"error": "An unknown error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 알림 생성 헬퍼 함수
def create_notification(recipient, actor, notification_type, post, comment=None):
    """알림을 생성합니다. 본인에게는 알림을 보내지 않습니다."""
    if recipient == actor:
        return None
    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=notification_type,
        post=post,
        comment=comment
    )


@extend_schema(tags=['알림'])
@extend_schema_view(
    get=extend_schema(
        summary="알림 목록 조회",
        description="로그인한 사용자의 알림 목록을 조회합니다.",
    )
)
class NotificationListAPIView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).order_by('-created_at')[:50]


@extend_schema(tags=['알림'])
class NotificationUnreadCountAPIView(APIView):
    """읽지 않은 알림 개수를 반환합니다."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="읽지 않은 알림 개수",
        description="로그인한 사용자의 읽지 않은 알림 개수를 반환합니다.",
    )
    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({'unread_count': count})


@extend_schema(tags=['알림'])
class NotificationMarkReadAPIView(APIView):
    """알림을 읽음으로 표시합니다."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="알림 읽음 처리",
        description="특정 알림 또는 전체 알림을 읽음으로 표시합니다.",
    )
    def post(self, request, notification_id=None):
        if notification_id:
            # 특정 알림 읽음 처리
            notification = get_object_or_404(
                Notification, id=notification_id, recipient=request.user
            )
            notification.is_read = True
            notification.save()
        else:
            # 전체 알림 읽음 처리
            Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({'success': True})


@extend_schema(tags=['임시저장'])
class DraftRetrieveCreateAPIView(generics.GenericAPIView):
    """사용자 게시글 작성 버퍼 조회 및 저장"""
    permission_classes = [IsAuthenticated]
    serializer_class = DraftSerializer

    @extend_schema(
        summary="임시저장 버퍼 조회",
        description="사용자의 작성 중인 게시글 버퍼를 조회합니다.",
        responses={
            200: DraftSerializer,
            404: OpenApiResponse(description="임시저장 데이터가 없습니다.")
        }
    )
    def get(self, request):
        """사용자 버퍼 조회"""
        try:
            draft = Draft.objects.get(author=request.user)
            serializer = self.get_serializer(draft)
            return Response(serializer.data)
        except Draft.DoesNotExist:
            return Response({'detail': 'No draft found'}, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(
        summary="임시저장 버퍼 생성/업데이트",
        description="게시글을 임시저장합니다. 사용자당 하나의 버퍼만 유지됩니다.",
        request=DraftSerializer,
        responses={
            200: DraftSerializer,
            201: DraftSerializer
        }
    )
    def post(self, request):
        """버퍼 생성/업데이트 (upsert)"""
        try:
            draft = Draft.objects.get(author=request.user)
            serializer = self.get_serializer(draft, data=request.data, partial=True, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Draft.DoesNotExist:
            serializer = self.get_serializer(data=request.data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['임시저장'])
class DraftDeleteAPIView(APIView):
    """임시저장 버퍼 삭제"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="임시저장 버퍼 삭제",
        description="사용자의 작성 중인 게시글 버퍼를 삭제합니다.",
        responses={
            204: OpenApiResponse(description="삭제 성공"),
            404: OpenApiResponse(description="임시저장 데이터가 없습니다.")
        }
    )
    def delete(self, request):
        try:
            draft = Draft.objects.get(author=request.user)
            draft.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Draft.DoesNotExist:
            return Response({'detail': 'No draft found'}, status=status.HTTP_404_NOT_FOUND)
