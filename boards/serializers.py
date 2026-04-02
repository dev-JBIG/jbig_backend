import re
import html
import logging

import boto3
import bleach
from botocore.client import Config
from botocore.exceptions import ClientError

from django.conf import settings
from django.db import transaction
from rest_framework import serializers

from .models import Category, Board, Post, Comment, Notification, Draft, generate_anonymous_nickname

logger = logging.getLogger(__name__)

# Thread-local storage for S3 client (process/fork 안전)
import threading
_thread_local = threading.local()


def get_s3_client():
    """
    Thread-local S3 클라이언트 반환.
    각 스레드/프로세스별로 독립적인 클라이언트를 유지하여
    gunicorn prefork 등 멀티프로세스 환경에서도 안전하게 동작.
    """
    if not hasattr(_thread_local, 's3_client'):
        _thread_local.s3_client = boto3.client(
            's3',
            endpoint_url=settings.NCP_ENDPOINT_URL,
            aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
            aws_secret_access_key=settings.NCP_SECRET_KEY,
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
        )
    return _thread_local.s3_client


def get_presigned_attachments(attachments_list):
    """첨부파일 목록에 대해 presigned URL을 생성하는 공통 함수"""
    if not attachments_list or not isinstance(attachments_list, list):
        return []
    try:
        s3_client = get_s3_client()
    except Exception as e:
        logger.error(f"S3 클라이언트 생성 실패: {e}")
        return []

    presigned_attachments = []
    for item in attachments_list:
        file_key = item.get('path') or item.get('url')
        name = item.get('name')
        if not file_key or not name or not file_key.startswith("uploads/"):
            continue
        try:
            meta = s3_client.head_object(Bucket=settings.NCP_BUCKET_NAME, Key=file_key)
            presigned_attachments.append({
                "url": s3_client.generate_presigned_url('get_object', Params={'Bucket': settings.NCP_BUCKET_NAME, 'Key': file_key}, ExpiresIn=3600),
                "name": name,
                "size": meta.get('ContentLength')
            })
        except ClientError as e:
            logger.error(f"S3 에러 (Key: {file_key}): {e}")
    return presigned_attachments


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']


class RecursiveField(serializers.Serializer):
    def to_representation(self, value):
        serializer = self.parent.parent.__class__(value, context=self.context)
        return serializer.data


class BoardSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    read_permission = serializers.SerializerMethodField()
    post_permission = serializers.SerializerMethodField()
    comment_permission = serializers.SerializerMethodField()
    available_tags = serializers.JSONField(read_only=True)

    class Meta:
        model = Board
        fields = ['id', 'name', 'category', 'board_type', 'read_permission', 'post_permission', 'comment_permission', 'available_tags']

    def get_read_permission(self, instance):
        user = self.context['request'].user
        perm = getattr(instance, 'read_permission', 'staff')
        if perm == 'all':
            return True
        return user.is_authenticated and user.is_staff

    def get_post_permission(self, instance):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        perm = getattr(instance, 'post_permission', 'staff')
        if perm == 'all':
            return True
        return user.is_staff

    def get_comment_permission(self, instance):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        perm = getattr(instance, 'comment_permission', 'staff')
        if perm == 'all':
            return True
        return user.is_staff

class BoardIdNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Board
        fields = ['id', 'name', 'board_type', 'available_tags']

class CategoryWithBoardsSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source='name')
    boards = BoardIdNameSerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ['category', 'boards']

class CommentSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    author_semester = serializers.SerializerMethodField()
    children = RecursiveField(many=True, read_only=True)
    is_owner = serializers.SerializerMethodField()
    post_id = serializers.IntegerField(source='post.id', read_only=True)
    post_title = serializers.CharField(source='post.title', read_only=True)
    board_id = serializers.IntegerField(source='post.board.id', read_only=True)
    likes = serializers.SerializerMethodField()
    isLiked = serializers.SerializerMethodField()
    is_anonymous = serializers.BooleanField(required=False, default=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'post_id', 'post_title', 'user_id', 'author', 'author_semester', 'content', 'created_at', 'parent', 'children', 'is_owner', 'is_deleted', 'board_id', 'likes', 'isLiked', 'is_anonymous', 'can_delete']
        read_only_fields = ('user_id', 'author', 'author_semester', 'created_at', 'children', 'is_owner', 'is_deleted', 'post_id', 'post_title', 'board_id', 'likes', 'isLiked', 'can_delete')


    # 작성자 이름 파싱 로직
    def get_author(self, obj):
        # author가 None인 경우 처리
        if not obj.author:
            # guest_id가 있으면 비회원 댓글
            if obj.guest_id:
                # guest_id의 해시값을 user_id처럼 사용하여 무작위 닉네임 생성
                import hashlib
                guest_hash = int(hashlib.md5(obj.guest_id.encode()).hexdigest()[:8], 16)
                return generate_anonymous_nickname(guest_hash, obj.post.id)
            # guest_id가 없으면 탈퇴한 사용자
            return "탈퇴한 사용자"
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글인 경우
        if obj.is_anonymous:
            # 로그인한 회원은 실명을 볼 수 있음
            if user and user.is_authenticated:
                return obj.author.username
            else:
                # 비회원은 무작위 닉네임을 봄 (익명성 보장을 위해 실제 semester 사용 안 함)
                # 같은 게시글 내에서는 동일한 닉네임 유지를 위해 post.id 사용
                return generate_anonymous_nickname(obj.author.id, obj.post.id)
        else:
            # 익명이 아닌 경우 실명 표시
            return obj.author.username


    def get_user_id(self, obj):
        # author가 None인 경우 처리
        if not obj.author:
            # guest_id가 있으면 비회원, 없으면 탈퇴한 사용자
            return '비회원' if obj.guest_id else '탈퇴한사용자'
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글인 경우
        if obj.is_anonymous:
            # 로그인한 회원은 실제 user_id를 볼 수 있음
            if user and user.is_authenticated:
                return obj.author.email.split('@')[0]
            else:
                # 비회원은 익명으로 표시
                return '익명'
        else:
            return obj.author.email.split('@')[0]
    
    def get_author_semester(self, obj):
        # author가 None인 경우 빈 문자열 반환 (비회원 또는 탈퇴한 사용자)
        if not obj.author:
            return ''
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글이고 비회원인 경우 학기 정보 숨김 (빈 문자열 반환)
        if obj.is_anonymous and not (user and user.is_authenticated):
            return ''
        
        # semester가 None이면 빈 문자열 반환
        return obj.author.semester if obj.author.semester is not None else ''

    def get_is_owner(self, obj):
        # 탈퇴한 사용자의 게시글/댓글은 소유자가 없음
        if not obj.author:
            return False
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.author == user
        return False

    def get_can_delete(self, obj):
        """삭제 권한: 본인 댓글이거나, 글 작성자가 비회원 댓글을 삭제할 때"""
        user = self.context.get('request').user
        if not user or not user.is_authenticated:
            return False
        # 본인 댓글
        if obj.author == user:
            return True
        # 비회원 댓글이고 글 작성자인 경우
        if obj.author is None and obj.post.author == user:
            return True
        return False

    def get_likes(self, obj):
        return obj.likes.count()

    def get_isLiked(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.likes.filter(pk=user.pk).exists()
        return False

    def validate_content(self, value):
        sanitized_content = bleach.clean(value, tags=[], strip=True).strip()
        # bleach가 &를 &amp;로 변환하므로 다시 복원
        sanitized_content = html.unescape(sanitized_content)
        if not sanitized_content:
            raise serializers.ValidationError("Content cannot be empty.")
        return sanitized_content
    

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        
        # 대댓글(children)을 created_at 기준으로 정렬 (오래된 순, 최신 댓글이 아래에)
        if 'children' in representation and representation['children']:
            from datetime import datetime
            def get_sort_key(x):
                created_at = x.get('created_at', '')
                if isinstance(created_at, str):
                    try:
                        # ISO 8601 형식 문자열을 datetime으로 변환
                        return datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        return datetime.min
                return created_at if created_at else datetime.min
            
            representation['children'] = sorted(
                representation['children'],
                key=get_sort_key,
                reverse=False
            )
        
        if instance.is_deleted:
            representation['content'] = '삭제된 댓글입니다.'
            representation['author'] = '알 수 없는 사용자'
            representation['user_id'] = '알 수 없는 사용자'
        return representation

class PostListSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    author_semester = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comment_count = serializers.SerializerMethodField()
    attachment_paths = serializers.SerializerMethodField()
    board_id = serializers.IntegerField(source='board.id', read_only=True)
    board_name = serializers.CharField(source='board.name', read_only=True)
    is_anonymous = serializers.BooleanField(read_only=True)
    tag = serializers.CharField(read_only=True)
    recruitment_info = serializers.SerializerMethodField()


    class Meta:
        model = Post
        fields = ['id', 'board_post_id', 'title', 'user_id', 'author', 'author_semester', 'created_at', 'views', 'likes_count', 'comment_count', 'attachment_paths', 'board_id', 'board_name', 'is_anonymous', 'tag', 'recruitment_info']

    def get_recruitment_info(self, obj):
        """모집 게시글이면 모집 요약 정보 반환"""
        recruitment = getattr(obj, 'recruitment', None)
        if recruitment is None:
            # select_related가 안 된 경우 DB 조회 방지
            if hasattr(obj, '_prefetched_objects_cache'):
                return None
            try:
                recruitment = obj.recruitment
            except Exception:
                return None
        if recruitment is None:
            return None
        return {
            'recruitment_type': recruitment.recruitment_type,
            'recruitment_type_display': recruitment.get_recruitment_type_display(),
            'status': recruitment.status,
            'status_display': recruitment.get_status_display(),
            'max_members': recruitment.max_members,
            'accepted_count': recruitment.accepted_count,
            'deadline': recruitment.deadline,
        }

    def get_author(self, obj):
        # 탈퇴한 사용자 처리
        if not obj.author:
            return "탈퇴한 사용자"
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글인 경우
        if obj.is_anonymous:
            # 로그인한 회원은 실명을 볼 수 있음
            if user and user.is_authenticated:
                return obj.author.username
            else:
                # 비회원은 무작위 닉네임을 봄 (익명성 보장을 위해 실제 semester 사용 안 함)
                return generate_anonymous_nickname(obj.author.id, obj.id)
        else:
            # 익명이 아닌 경우 실명 표시
            return obj.author.username


    def get_user_id(self, obj):
        # 탈퇴한 사용자 처리
        if not obj.author:
            return '탈퇴한사용자'
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글인 경우
        if obj.is_anonymous:
            # 로그인한 회원은 실제 user_id를 볼 수 있음
            if user and user.is_authenticated:
                return obj.author.email.split('@')[0]
            else:
                # 비회원은 익명으로 표시
                return '익명'
        else:
            return obj.author.email.split('@')[0]
    
    def get_author_semester(self, obj):
        # 탈퇴한 사용자 처리
        if not obj.author:
            return ''
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글이고 비회원인 경우 학기 정보 숨김 (빈 문자열 반환)
        if obj.is_anonymous and not (user and user.is_authenticated):
            return ''
        
        return obj.author.semester

    def get_comment_count(self, obj):
        return obj.comments.count()

    def get_attachment_paths(self, obj):
        return get_presigned_attachments(obj.attachment_paths)


def normalize_ncp_urls(content):
    """NCP presigned URL을 ncp-key:// 형식으로 정규화

    다양한 NCP 엔드포인트/버킷명을 지원하도록 유연한 패턴 사용
    """
    if not content:
        return content
    # 다양한 NCP Object Storage URL 패턴 지원:
    # - https://kr.object.ncloudstorage.com/버킷명/uploads/...
    # - https://*.ncloudstorage.com/버킷명/uploads/...
    pattern = r'https://[^/]+\.ncloudstorage\.com/[^/]+/(uploads/[^?\s\)]+)(?:\?[^\s\)]*)?'
    return re.sub(pattern, r'ncp-key://\1', content)


class PostCreateUpdateSerializer(serializers.ModelSerializer):
    attachment_paths = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    content_md = serializers.CharField(write_only=True, required=False, allow_blank=True)
    board_id = serializers.IntegerField(write_only=True, required=False)
    is_anonymous = serializers.BooleanField(required=False, default=True)
    tag = serializers.CharField(required=False, allow_blank=True, default='')
    recruitment = serializers.DictField(write_only=True, required=False)

    class Meta:
        model = Post
        fields = ['title', 'content_md', 'attachment_paths', 'post_type', 'board_id', 'is_anonymous', 'tag', 'recruitment']


    def _resolve_board(self, validated_data):
        board_id = validated_data.get('board_id')
        if board_id:
            return Board.objects.filter(id=board_id).first()
        view = self.context.get('view')
        if view and hasattr(view, 'kwargs'):
            board_id = view.kwargs.get('board_id')
            if board_id:
                return Board.objects.filter(id=board_id).first()
        if getattr(self, 'instance', None):
            return self.instance.board
        return None

    def _is_photo_board(self, board: Board | None) -> bool:
        if not board:
            return False
        return board.board_type == Board.BoardType.PHOTO_ALBUM or board.name == "사진첩"

    def _is_image_name(self, name: str) -> bool:
        return bool(re.search(r'\.(png|jpe?g|gif|webp|bmp|svg)$', name, re.IGNORECASE))

    def validate(self, attrs):
        board = self._resolve_board(attrs)
        if self._is_photo_board(board):
            content = attrs.get('content_md')
            if content is None and getattr(self, 'instance', None):
                content = self.instance.content_md or ''
            if content and str(content).strip():
                raise serializers.ValidationError({"content_md": "사진첩 게시판은 본문을 작성할 수 없습니다."})

            attachments = attrs.get('attachment_paths')
            if attachments is None and getattr(self, 'instance', None):
                attachments = self.instance.attachment_paths or []

            if not attachments:
                raise serializers.ValidationError({"attachment_paths": "사진첩 게시판에는 사진을 최소 1장 이상 업로드해야 합니다."})

            for item in attachments:
                if not isinstance(item, dict):
                    raise serializers.ValidationError({"attachment_paths": "잘못된 첨부파일 형식입니다."})
                name = item.get('name') or ''
                path = item.get('path') or ''
                candidate = name or path
                if not self._is_image_name(candidate):
                    raise serializers.ValidationError({"attachment_paths": "사진첩 게시판에는 이미지 파일만 업로드할 수 있습니다."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        attachment_paths = validated_data.pop('attachment_paths', [])
        content_md = validated_data.pop('content_md', '')
        recruitment_data = validated_data.pop('recruitment', None)

        post = Post(**validated_data)
        post.content_md = normalize_ncp_urls(content_md)
        post.attachment_paths = attachment_paths
        post.save()
        post.update_search_vector()
        if post.search_vector is not None:
            post.save(update_fields=['search_vector'])

        # 모집 데이터가 있으면 Recruitment 생성
        if recruitment_data and validated_data.get('tag') == '팀원모집':
            from recruitments.models import Recruitment
            from recruitments.serializers import RecruitmentCreateSerializer
            rec_serializer = RecruitmentCreateSerializer(data=recruitment_data)
            rec_serializer.is_valid(raise_exception=True)
            rec_serializer.save(post=post)

        return post

    def update(self, instance, validated_data):
        attachment_paths = validated_data.pop('attachment_paths', None)
        content_md = validated_data.pop('content_md', None)
        board_id = validated_data.pop('board_id', None)
        validated_data.pop('recruitment', None)  # 모집 수정은 별도 API로

        # 태그가 '팀원모집'에서 다른 태그로 변경되면 Recruitment 삭제
        new_tag = validated_data.get('tag')
        if new_tag is not None and new_tag != '팀원모집' and hasattr(instance, 'recruitment'):
            try:
                instance.recruitment.delete()
            except Exception:
                pass

        if content_md is not None:
            instance.content_md = normalize_ncp_urls(content_md)

        if attachment_paths is not None:
            instance.attachment_paths = attachment_paths

        if board_id is not None:
            new_board = Board.objects.filter(id=board_id).first()
            if new_board and new_board != instance.board:
                # 게시판이 실제로 변경되는 경우, board_post_id를 초기화하여 새로 할당되도록 함
                instance.board = new_board
                instance.board_post_id = None

        instance = super().update(instance, validated_data)
        instance.update_search_vector()
        if instance.search_vector is not None:
            instance.save(update_fields=['search_vector'])
        return instance

class PostDetailSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    author_semester = serializers.SerializerMethodField()
    board = BoardSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    attachment_paths = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    content_md = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    is_anonymous = serializers.BooleanField(read_only=True)
    tag = serializers.CharField(read_only=True)
    recruitment = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'board_post_id', 'title', 'content_md', 'user_id', 'author', 'author_semester',
            'created_at', 'updated_at', 'views', 'board', 'comments', 'attachment_paths',
            'likes_count', 'comments_count', 'is_liked', 'post_type', 'is_owner', 'is_anonymous',
            'tag', 'recruitment'
        ]

    def get_recruitment(self, obj):
        try:
            rec = obj.recruitment
        except Exception:
            return None
        if rec is None:
            return None
        from recruitments.serializers import RecruitmentDetailSerializer
        return RecruitmentDetailSerializer(rec, context=self.context).data

    def get_author(self, obj):
        # 탈퇴한 사용자 처리
        if not obj.author:
            return "탈퇴한 사용자"
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글인 경우
        if obj.is_anonymous:
            # 로그인한 회원은 실명을 볼 수 있음
            if user and user.is_authenticated:
                return obj.author.username
            else:
                # 비회원은 무작위 닉네임을 봄 (익명성 보장을 위해 실제 semester 사용 안 함)
                return generate_anonymous_nickname(obj.author.id, obj.id)
        else:
            # 익명이 아닌 경우 실명 표시
            return obj.author.username


    def get_user_id(self, obj):
        # 탈퇴한 사용자 처리
        if not obj.author:
            return '탈퇴한사용자'
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글인 경우
        if obj.is_anonymous:
            # 로그인한 회원은 실제 user_id를 볼 수 있음
            if user and user.is_authenticated:
                return obj.author.email.split('@')[0]
            else:
                # 비회원은 익명으로 표시
                return '익명'
        else:
            return obj.author.email.split('@')[0]
    
    def get_author_semester(self, obj):
        # 탈퇴한 사용자 처리
        if not obj.author:
            return ''
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # 익명 작성글이고 비회원인 경우 학기 정보 숨김 (빈 문자열 반환)
        if obj.is_anonymous and not (user and user.is_authenticated):
            return ''
        
        return obj.author.semester

    def get_comments(self, obj):
        # 최상위 댓글만 가져오고 created_at 기준 오래된 순으로 정렬 (최신 댓글이 아래에)
        # likes와 children(답글)의 likes도 함께 prefetch
        comments = obj.comments.filter(parent__isnull=True).prefetch_related('likes', 'children__likes').order_by('created_at')
        return CommentSerializer(comments, many=True, context=self.context).data

    def get_comments_count(self, obj):
        return obj.comments.count()

    def get_is_liked(self, obj):
        user = self.context['request'].user
        return user.is_authenticated and obj.likes.filter(pk=user.pk).exists()

    def get_is_owner(self, obj):
        # 탈퇴한 사용자의 게시글/댓글은 소유자가 없음
        if not obj.author:
            return False
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.author == user
        return False

    def get_content_md(self, obj):
        raw_md = obj.content_md
        if not raw_md:
            return ""

        def replace_with_public_url(match):
            alt_text = match.group(1)
            file_key = match.group(2)
            if not file_key:
                return match.group(0)
            url = f"{settings.NCP_ENDPOINT_URL}/{settings.NCP_BUCKET_NAME}/{file_key}"
            return f"{alt_text}({url})"

        pattern = r'(!\[.*?\])\(ncp-key://(uploads/[^\s\)]+)\)'
        return re.sub(pattern, replace_with_public_url, raw_md, flags=re.DOTALL)

    def get_attachment_paths(self, obj):
        return get_presigned_attachments(obj.attachment_paths)


class PostListResponseSerializer(serializers.Serializer):
    board = BoardSerializer()
    posts = PostListSerializer(many=True)
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)

class CategoryListResponseSerializer(serializers.Serializer):
    total_post_count = serializers.IntegerField()
    categories = CategoryWithBoardsSerializer(many=True)


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    actor_semester = serializers.SerializerMethodField()
    post_title = serializers.SerializerMethodField()
    post_id = serializers.SerializerMethodField()
    board_id = serializers.SerializerMethodField()
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    comment_content = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'notification_type_display',
            'actor_name', 'actor_semester', 'post_id', 'post_title', 'board_id',
            'comment_content', 'is_read', 'created_at'
        ]

    def get_actor_name(self, obj):
        # 비회원 댓글인 경우만 "익명" 처리
        if not obj.actor:
            return "익명"
        
        # 알림은 게시글 작성자(회원)에게 가므로 항상 실명 표시
        # is_anonymous는 비회원에게 어떻게 보일지를 결정하는 것이지 알림과는 무관
        return obj.actor.username

    def get_actor_semester(self, obj):
        # 비회원인 경우만 0 반환
        if not obj.actor:
            return 0
        
        # 알림은 회원에게 가므로 항상 기수 표시
        return obj.actor.semester

    def get_post_title(self, obj):
        if not obj.post:
            return "삭제된 게시글"
        return obj.post.title

    def get_post_id(self, obj):
        if not obj.post:
            return None
        return obj.post.id

    def get_board_id(self, obj):
        if not obj.post or not obj.post.board:
            return None
        return obj.post.board.id

    def get_comment_content(self, obj):
        if obj.comment and not obj.comment.is_deleted:
            content = obj.comment.content
            return content[:50] + '...' if len(content) > 50 else content
        return None


class DraftSerializer(serializers.ModelSerializer):
    board_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    board_name = serializers.CharField(source='board.name', read_only=True, allow_null=True)

    class Meta:
        model = Draft
        fields = ['board_id', 'board_name', 'title', 'content_md', 'uploaded_paths', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at', 'board_name']

    def to_representation(self, instance):
        """조회 시 ncp-key:// URL을 퍼블릭 URL로 변환"""
        data = super().to_representation(instance)
        raw_md = data.get('content_md', '')
        if not raw_md:
            return data

        def replace_with_public_url(match):
            alt_text = match.group(1)
            file_key = match.group(2)
            if not file_key:
                return match.group(0)
            url = f"{settings.NCP_ENDPOINT_URL}/{settings.NCP_BUCKET_NAME}/{file_key}"
            return f"{alt_text}({url})"

        pattern = r'(!\[.*?\])\(ncp-key://(uploads/[^\s\)]+)\)'
        data['content_md'] = re.sub(pattern, replace_with_public_url, raw_md, flags=re.DOTALL)
        return data

    def create(self, validated_data):
        board_id = validated_data.pop('board_id', None)
        board = Board.objects.filter(id=board_id).first() if board_id else None
        author = self.context['request'].user
        
        # 사용자당 하나의 버퍼 (upsert 동작)
        draft, created = Draft.objects.update_or_create(
            author=author,
            defaults={
                'board': board,
                'title': validated_data.get('title', ''),
                'content_md': normalize_ncp_urls(validated_data.get('content_md', '')),
                'uploaded_paths': validated_data.get('uploaded_paths', [])
            }
        )
        return draft

    def update(self, instance, validated_data):
        board_id = validated_data.pop('board_id', None)
        if board_id is not None:
            instance.board = Board.objects.filter(id=board_id).first() if board_id else None
        
        instance.title = validated_data.get('title', instance.title)
        content_md = validated_data.get('content_md', instance.content_md)
        instance.content_md = normalize_ncp_urls(content_md)
        instance.uploaded_paths = validated_data.get('uploaded_paths', instance.uploaded_paths)
        instance.save()
        return instance
