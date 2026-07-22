import re
import logging

import bleach
from botocore.exceptions import ClientError

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.urls import reverse
from rest_framework import serializers

from .models import Category, Board, Post, Comment, CommentLike, Notification, Draft, generate_anonymous_nickname
from jbig_backend.storage import get_s3_client, public_media_url

logger = logging.getLogger(__name__)

from bleach.css_sanitizer import CSSSanitizer

# content_md / 마크다운 본문에 허용할 HTML 태그와 속성 화이트리스트.
# 프론트엔드가 rehype-raw로 raw HTML을 렌더하므로, 저장 전 서버에서도 한 번 더 필터링한다.
ALLOWED_MD_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'del', 'div', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'i', 'img', 'ins', 'kbd', 'li', 'mark', 'ol', 'p', 'pre',
    'q', 's', 'samp', 'small', 'span', 'strong', 'sub', 'sup', 'table', 'tbody', 'td',
    'tfoot', 'th', 'thead', 'tr', 'u', 'ul',
}
ALLOWED_MD_ATTRIBUTES = {
    '*': ['class'],
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'div': ['style'],
    'span': ['style'],
}
ALLOWED_MD_PROTOCOLS = ['http', 'https', 'mailto', 'data']
_MD_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=['text-align', 'color', 'background-color'],
)


def sanitize_markdown(value: str) -> str:
    if not value:
        return ''
    return bleach.clean(
        value,
        tags=ALLOWED_MD_TAGS,
        attributes=ALLOWED_MD_ATTRIBUTES,
        protocols=ALLOWED_MD_PROTOCOLS,
        strip=True,
        css_sanitizer=_MD_CSS_SANITIZER,
    )


def is_post_media_gated(post) -> bool:
    """해당 게시글의 미디어(첨부/본문 이미지)를 권한 게이트해야 하는지 판정한다.

    - 게시판 공개범위가 'member'/'staff'이거나,
    - 글 자체가 비공개 유형(스태프전용/사유서)이면 게이트한다.
    첨부 URL 변환과 본문 이미지 토큰화가 같은 기준을 쓰도록 한 곳에서 판정해,
    둘 사이의 판정이 어긋나 한쪽만 노출되는 일을 막는다. post=None 이면 False.
    """
    if post is None:
        return False
    board = getattr(post, 'board', None)
    read_perm = getattr(board, 'read_permission', 'all')
    private_post_type = getattr(post, 'post_type', None) in (
        Post.PostType.STAFF_ONLY, Post.PostType.JUSTIFICATION_LETTER,
    )
    return read_perm in ('member', 'staff') or private_post_type


def get_presigned_attachments(attachments_list, include_size=True, post=None, request=None):
    """첨부파일 목록을 클라이언트용 URL + 메타로 변환하는 공통 함수.

    - 공개('all') 게시판의 일반 글: 고정 공개 URL(public_media_url) → CDN 캐시 동작.
    - 비공개 게시판('member'/'staff') 또는 비공개 글 유형(스태프전용/사유서):
      권한 게이트된 백엔드 다운로드 엔드포인트 URL로 바꿔 내보내고 `gated=True`를
      표시한다. 원본 스토리지 URL은 노출하지 않는다.
    include_size=True일 때만 size 표시를 위해 head_object를 호출한다.
    """
    if not attachments_list or not isinstance(attachments_list, list):
        return []

    # 게시판이 공개여도 글 자체가 비공개 유형(사유서/스태프전용)이면 첨부를 게이트한다.
    # 판정 기준은 is_post_media_gated 하나로 통일해 본문 이미지 토큰화와 어긋나지 않게 한다.
    gated = is_post_media_gated(post) and getattr(post, 'id', None) is not None

    s3_client = None
    if include_size:
        try:
            s3_client = get_s3_client()
        except Exception as e:
            logger.error(f"S3 클라이언트 생성 실패: {e}")
            return []

    presigned_attachments = []
    # 다운로드 엔드포인트는 원본 attachment_paths의 인덱스를 사용하므로 enumerate로 원본 인덱스를 유지한다.
    for idx, item in enumerate(attachments_list):
        if not isinstance(item, dict):
            continue
        file_key = item.get('path') or item.get('url')
        name = item.get('name')
        if not file_key or not name:
            continue
        file_key = file_key.replace('\\', '/')  # 레거시 역슬래시 key 정규화
        if not file_key.startswith("uploads/"):
            continue
        if gated:
            path = reverse('post-attachment-download', kwargs={'post_id': post.id, 'index': idx})
            url = request.build_absolute_uri(path) if request is not None else path
        else:
            url = public_media_url(file_key)
        attachment = {
            "url": url,
            "name": name,
            "gated": gated,
        }
        if include_size:
            try:
                meta = s3_client.head_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=file_key)
                attachment["size"] = meta.get('ContentLength')
            except ClientError as e:
                logger.error(f"S3 에러 (Key: {file_key}): {e}")
                continue
        presigned_attachments.append(attachment)
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

    # read_permission은 하위호환을 위해 "현재 사용자가 읽을 수 있는가"(bool)를 유지하고,
    # read_scope는 원본 공개범위 값('all'/'member'/'staff')을 그대로 노출한다.
    read_scope = serializers.CharField(source='read_permission', read_only=True)

    class Meta:
        model = Board
        fields = ['id', 'name', 'category', 'board_type', 'form_type', 'read_permission', 'read_scope', 'post_permission', 'comment_permission', 'available_tags']

    def get_read_permission(self, instance):
        user = self.context['request'].user
        perm = getattr(instance, 'read_permission', 'staff')
        if perm == 'all':
            return True
        if perm == 'member':
            return user.is_authenticated
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

class BoardAdminSerializer(serializers.ModelSerializer):
    """관리자 게시판 관리 화면용. read_permission(공개범위)만 편집 가능하다."""
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Board
        fields = [
            'id', 'name', 'category', 'category_name', 'board_type', 'form_type',
            'read_permission', 'post_permission', 'comment_permission',
        ]
        read_only_fields = [
            'id', 'name', 'category', 'category_name', 'board_type', 'form_type',
            'post_permission', 'comment_permission',
        ]

    def validate_read_permission(self, value):
        # 사진첩은 이미지가 <img src>로 직접 로드되어(인증 헤더 없음) 비공개로
        # 전환하면 화면이 깨진다. 게이트 렌더링을 지원하기 전까지 전체공개만 허용.
        board = self.instance
        if board and board.board_type == Board.BoardType.PHOTO_ALBUM and value != 'all':
            raise serializers.ValidationError(
                '사진첩 게시판은 이미지 렌더링 특성상 전체공개만 지원합니다.'
            )
        return value


class BoardIdNameSerializer(serializers.ModelSerializer):
    latest_post_created_at = serializers.SerializerMethodField()

    class Meta:
        model = Board
        # read_permission(공개범위)을 그대로 노출해 사이드바에서 회원전용/스태프 게시판에
        # 잠금 표시나 로그인 유도를 할 수 있게 한다.
        fields = ['id', 'name', 'board_type', 'form_type', 'available_tags', 'latest_post_created_at', 'read_permission']

    def get_latest_post_created_at(self, obj):
        value = getattr(obj, 'latest_post_created_at', None)
        if value is None:
            return None
        return serializers.DateTimeField().to_representation(value)

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
        # likes 가 prefetch 된 경우 캐시를 사용(추가 쿼리 0). 아니면 count 쿼리 1회.
        return len(obj.likes.all())

    def get_isLiked(self, obj):
        # 상위 시리얼라이저가 미리 계산해 넘긴 "내가 누른 댓글 id 집합"이 있으면
        # 댓글마다 .exists() 쿼리를 반복하지 않는다.
        liked_ids = self.context.get('liked_comment_ids')
        if liked_ids is not None:
            return obj.id in liked_ids
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.likes.filter(pk=user.pk).exists()
        return False

    def validate_content(self, value):
        sanitized_content = bleach.clean(value, tags=[], strip=True).strip()
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

class PostSummarySerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    author_semester = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    board_id = serializers.IntegerField(source='board.id', read_only=True)
    board_name = serializers.CharField(source='board.name', read_only=True)
    is_anonymous = serializers.BooleanField(read_only=True)
    tag = serializers.CharField(read_only=True)
    recruitment_info = serializers.SerializerMethodField()


    class Meta:
        model = Post
        fields = ['id', 'board_post_id', 'title', 'user_id', 'author', 'author_semester', 'created_at', 'views', 'likes_count', 'comment_count', 'board_id', 'board_name', 'post_type', 'is_anonymous', 'tag', 'recruitment_info']

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

class PostListSerializer(PostSummarySerializer):
    attachment_paths = serializers.SerializerMethodField()

    class Meta(PostSummarySerializer.Meta):
        fields = PostSummarySerializer.Meta.fields + ['attachment_paths']

    def get_attachment_paths(self, obj):
        return get_presigned_attachments(
            obj.attachment_paths, include_size=False,
            post=obj, request=self.context.get('request'),
        )


class PhotoPostSummarySerializer(serializers.ModelSerializer):
    attachment_paths = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ['id', 'title', 'created_at', 'attachment_paths']

    def get_attachment_paths(self, obj):
        return get_presigned_attachments(
            obj.attachment_paths, include_size=False,
            post=obj, request=self.context.get('request'),
        )


def normalize_media_urls(content):
    """본문의 퍼블릭/CDN 이미지 URL을 media-key:// 키 형식으로 정규화한다.

    R2 엔드포인트, Cloudflare CDN 커스텀 도메인 등 어떤 스토리지의 퍼블릭
    URL이든 ".../uploads/<key>" 형태이면 내부 키(media-key://uploads/...)로
    환원해 저장한다. 도메인이 바뀌어도 저장 포맷이 일정해, 첨부 삭제 추적과
    공개 URL 변환이 일관되게 동작한다.
    (media-key:// 는 스토리지 벤더와 무관한 내부 키 마커다.)
    """
    if not content:
        return content
    pattern = r'https?://[^\s\)]+?/(uploads/[^?\s\)]+)(?:\?[^\s\)]*)?'
    return re.sub(pattern, r'media-key://\1', content)


MAX_ATTACHMENTS_PER_POST = 30


class PostCreateUpdateSerializer(serializers.ModelSerializer):
    attachment_paths = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        max_length=MAX_ATTACHMENTS_PER_POST,
    )
    content_md = serializers.CharField(write_only=True, required=False, allow_blank=True)
    board_id = serializers.IntegerField(write_only=True, required=False)
    is_anonymous = serializers.BooleanField(required=False, default=True)
    tag = serializers.CharField(required=False, allow_blank=True, default='')
    recruitment = serializers.DictField(write_only=True, required=False)

    class Meta:
        model = Post
        fields = ['title', 'content_md', 'attachment_paths', 'post_type', 'board_id', 'is_anonymous', 'tag', 'recruitment']

    def validate_attachment_paths(self, value):
        """
        첨부 경로는 반드시 요청자 본인이 업로드한 파일만 허용한다.
        경로 포맷: `uploads/<y>/<m>/<d>/<user_id>/<uuid>.<ext>` — 서버에서 생성되는 형식.
        타인의 파일을 첨부 후 게시글 삭제 시점에 해당 파일이 스토리지에서 연쇄 삭제되는
        cross-user file-deletion 공격을 차단한다.
        """
        request = self.context.get('request')
        user_id = getattr(getattr(request, 'user', None), 'id', None)
        if user_id is None:
            raise serializers.ValidationError('인증이 필요합니다.')

        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('각 첨부 항목은 객체여야 합니다.')
            path = (item.get('path') or '').strip()
            if not path.startswith('uploads/'):
                raise serializers.ValidationError('잘못된 첨부 경로입니다.')
            if '..' in path.split('/') or path.startswith('/'):
                raise serializers.ValidationError('잘못된 첨부 경로입니다.')
            parts = path.split('/')
            if len(parts) < 6:
                raise serializers.ValidationError('잘못된 첨부 경로 형식입니다.')
            try:
                owner_id = int(parts[4])
            except (TypeError, ValueError):
                raise serializers.ValidationError('잘못된 첨부 경로 형식입니다.')
            if owner_id != user_id:
                raise serializers.ValidationError('본인이 업로드한 파일만 첨부할 수 있습니다.')
        return value


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
        post.content_md = sanitize_markdown(normalize_media_urls(content_md))
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
        # post_type은 board_type 기반으로 서버에서 결정되는 값이므로 수정 요청에서 제거한다.
        validated_data.pop('post_type', None)

        # 태그가 '팀원모집'에서 다른 태그로 변경되면 Recruitment 삭제
        new_tag = validated_data.get('tag')
        if new_tag is not None and new_tag != '팀원모집' and hasattr(instance, 'recruitment'):
            try:
                instance.recruitment.delete()
            except Exception:
                pass

        if content_md is not None:
            instance.content_md = sanitize_markdown(normalize_media_urls(content_md))

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
        # 최상위 댓글만 가져오고 created_at 기준 오래된 순으로 정렬 (최신 댓글이 아래에).
        # author/post/board 를 select_related, likes·children 을 prefetch 해서
        # 댓글 트리 직렬화 중 per-comment N+1(작성자·게시글·좋아요)을 제거한다.
        child_qs = (
            Comment.objects
            .select_related('author', 'post', 'post__board')
            .prefetch_related('likes')
            .order_by('created_at')
        )
        comments = list(
            obj.comments.filter(parent__isnull=True)
            .select_related('author', 'post', 'post__board')
            .prefetch_related('likes', Prefetch('children', queryset=child_qs))
            .order_by('created_at')
        )

        # "내가 좋아요 누른 댓글 id"를 트리 전체에 대해 1쿼리로 미리 계산 →
        # 각 댓글의 isLiked 가 exists() 쿼리를 반복하지 않도록 context 로 전달.
        context = self.context
        request = context.get('request')
        user = request.user if request else None
        if user and user.is_authenticated:
            all_ids = []
            for c in comments:
                all_ids.append(c.id)
                all_ids.extend(child.id for child in c.children.all())
            liked_ids = set(
                CommentLike.objects
                .filter(user=user, comment_id__in=all_ids)
                .values_list('comment_id', flat=True)
            )
            context = {**context, 'liked_comment_ids': liked_ids}

        return CommentSerializer(comments, many=True, context=context).data

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

        pattern = r'(!\[.*?\])\(media-key://(uploads[\\/][^\s\)]+)\)'

        # 비공개(회원전용/스태프/사유서·스태프전용 글)면 본문 인라인 이미지를 영구 공개 URL이
        # 아니라 서명된 단기 토큰 스트림 URL로 바꾼다. <img src>는 Authorization 헤더를
        # 못 실으므로 URL 자체에 서명 토큰을 넣어야 게이트가 성립한다. 첨부와 동일하게
        # is_post_media_gated 로 판정해 판정이 어긋나지 않게 한다.
        if is_post_media_gated(obj):
            # 순환 임포트 회피: 뷰의 토큰 생성 헬퍼를 지연 임포트.
            from .views import make_media_stream_url
            request = self.context.get('request')

            def replace_with_stream_url(match):
                alt_text = match.group(1)
                file_key = match.group(2)
                if not file_key:
                    return match.group(0)
                file_key = file_key.replace('\\', '/')  # 레거시 역슬래시 key 정규화
                path = make_media_stream_url(file_key)
                url = request.build_absolute_uri(path) if request is not None else path
                return f"{alt_text}({url})"

            return re.sub(pattern, replace_with_stream_url, raw_md, flags=re.DOTALL)

        # 공개 글은 기존대로 고정 공개 URL(public_media_url) → CDN 캐시가 동작한다.
        def replace_with_public_url(match):
            alt_text = match.group(1)
            file_key = match.group(2)
            if not file_key:
                return match.group(0)
            return f"{alt_text}({public_media_url(file_key)})"

        return re.sub(pattern, replace_with_public_url, raw_md, flags=re.DOTALL)

    def get_attachment_paths(self, obj):
        return get_presigned_attachments(
            obj.attachment_paths,
            post=obj, request=self.context.get('request'),
        )


class PostListResponseSerializer(serializers.Serializer):
    board = BoardSerializer()
    posts = PostSummarySerializer(many=True)
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
        """조회 시 media-key:// URL을 퍼블릭 URL로 변환"""
        data = super().to_representation(instance)
        raw_md = data.get('content_md', '')
        if not raw_md:
            return data

        def replace_with_public_url(match):
            alt_text = match.group(1)
            file_key = match.group(2)
            if not file_key:
                return match.group(0)
            return f"{alt_text}({public_media_url(file_key)})"

        pattern = r'(!\[.*?\])\(media-key://(uploads[\\/][^\s\)]+)\)'
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
                'content_md': sanitize_markdown(normalize_media_urls(validated_data.get('content_md', ''))),
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
        instance.content_md = sanitize_markdown(normalize_media_urls(content_md))
        instance.uploaded_paths = validated_data.get('uploaded_paths', instance.uploaded_paths)
        instance.save()
        return instance
