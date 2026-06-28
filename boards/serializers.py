import re
import logging
import ipaddress
import socket
from urllib.parse import urlparse

import bleach
import requests
from botocore.exceptions import ClientError

from django.conf import settings
from django.db import transaction
from rest_framework import serializers

from .models import Category, Board, Post, Comment, Notification, Draft, generate_anonymous_nickname
from jbig_backend.storage import get_s3_client, public_media_url

logger = logging.getLogger(__name__)

LINK_SHARE_BOARD_NAME = '링크공유'

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


def get_presigned_attachments(attachments_list):
    """첨부파일 목록을 공개(CDN) URL + 메타로 변환하는 공통 함수.

    URL은 고정 공개 URL(public_media_url)이라 CDN 캐시가 동작한다.
    size 표시를 위해 head_object 만 호출한다(메타데이터 조회, egress 아님).
    """
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
        if not file_key or not name:
            continue
        file_key = file_key.replace('\\', '/')  # 레거시 역슬래시 key 정규화
        if not file_key.startswith("uploads/"):
            continue
        try:
            meta = s3_client.head_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=file_key)
            presigned_attachments.append({
                "url": public_media_url(file_key),
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
        fields = ['id', 'name', 'category', 'board_type', 'form_type', 'read_permission', 'post_permission', 'comment_permission', 'available_tags']

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
        fields = ['id', 'name', 'board_type', 'form_type', 'available_tags']

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
    link_url = serializers.URLField(read_only=True)
    link_title = serializers.CharField(read_only=True)
    link_description = serializers.CharField(read_only=True)
    link_image_url = serializers.URLField(read_only=True)
    link_site_name = serializers.CharField(read_only=True)
    link_comment = serializers.SerializerMethodField()


    class Meta:
        model = Post
        fields = [
            'id', 'board_post_id', 'title', 'user_id', 'author', 'author_semester',
            'created_at', 'views', 'likes_count', 'comment_count', 'attachment_paths',
            'board_id', 'board_name', 'is_anonymous', 'tag', 'recruitment_info',
            'link_url', 'link_title', 'link_description', 'link_image_url', 'link_site_name',
            'link_comment'
        ]

    def get_link_comment(self, obj):
        if not is_link_share_board(obj.board):
            return ''
        return obj.content_md or ''

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


def is_link_share_board(board: Board | None) -> bool:
    if not board:
        return False
    return board.form_type == Board.FormType.LINK_SHARE or board.name == LINK_SHARE_BOARD_NAME


def _reject_private_or_invalid_url(value: str) -> str:
    url = (value or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise serializers.ValidationError('http 또는 https 링크만 입력할 수 있습니다.')

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise serializers.ValidationError('링크 주소를 확인할 수 없습니다.')

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise serializers.ValidationError('공개 인터넷 링크만 등록할 수 있습니다.')
    return url


def _truncate(value: str, max_length: int) -> str:
    value = re.sub(r'\s+', ' ', (value or '').strip())
    return value[:max_length]


def fetch_open_graph_metadata(url: str) -> dict[str, str]:
    """링크 미리보기(OG) 메타데이터를 Cloudflare Worker에 위임해 가져온다.

    원격 사이트 크롤링을 오리진 서버에서 직접 하지 않는다(egress IP 격리 · SSRF
    격리 · 워커 부하 방지 · 문자셋 처리). Worker가 fetch/파싱/캐싱을 담당하고
    백엔드는 결과만 받는다. 실패는 링크 저장을 막지 않는다(best-effort).
    """
    target = (url or '').strip()
    parsed = urlparse(target)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return {}

    worker_url = getattr(settings, 'OG_WORKER_URL', '')
    if not worker_url:
        # 미설정이면 미리보기만 생략하고 저장은 정상 진행
        return {}

    try:
        response = requests.get(
            worker_url,
            params={'url': target},
            headers={'X-OG-Secret': getattr(settings, 'OG_WORKER_SECRET', '')},
            timeout=(3, 8),
        )
        if response.status_code != 200:
            return {}
        data = response.json()
    except Exception as exc:
        logger.info("Open Graph fetch failed for %s: %s", url, exc)
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        'link_title': _truncate(data.get('title') or '', 300),
        'link_description': _truncate(data.get('description') or '', 1000),
        'link_image_url': _truncate(data.get('image') or '', 2048),
        'link_site_name': _truncate(data.get('siteName') or '', 200),
    }


class PostCreateUpdateSerializer(serializers.ModelSerializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
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
    link_url = serializers.URLField(required=False, allow_blank=True, max_length=2048)

    class Meta:
        model = Post
        fields = ['title', 'content_md', 'attachment_paths', 'post_type', 'board_id', 'is_anonymous', 'tag', 'recruitment', 'link_url']

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
        link_board = is_link_share_board(board)

        if link_board:
            link_url = attrs.get('link_url')
            if link_url is None and getattr(self, 'instance', None):
                link_url = self.instance.link_url
            if not link_url:
                raise serializers.ValidationError({"link_url": "링크 URL을 입력하세요."})
            attrs['link_url'] = _reject_private_or_invalid_url(link_url)

            attachments = attrs.get('attachment_paths')
            if attachments:
                raise serializers.ValidationError({"attachment_paths": "링크공유 게시판은 첨부파일을 사용할 수 없습니다."})
            return attrs

        if not getattr(self, 'instance', None) and not str(attrs.get('title', '')).strip():
            raise serializers.ValidationError({"title": "제목을 입력하세요."})

        if getattr(self, 'instance', None) and 'title' in attrs and not str(attrs.get('title', '')).strip():
            raise serializers.ValidationError({"title": "제목을 입력하세요."})

        if attrs.get('link_url'):
            raise serializers.ValidationError({"link_url": "링크 URL은 링크공유 게시판에서만 사용할 수 있습니다."})

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
        link_url = validated_data.pop('link_url', '').strip()
        board = validated_data.get('board')

        post = Post(**validated_data)
        post.content_md = sanitize_markdown(normalize_media_urls(content_md))
        if is_link_share_board(board):
            metadata = fetch_open_graph_metadata(link_url)
            parsed = urlparse(link_url)
            post.link_url = link_url
            post.link_title = metadata.get('link_title') or ''
            post.link_description = metadata.get('link_description') or ''
            post.link_image_url = metadata.get('link_image_url') or ''
            post.link_site_name = metadata.get('link_site_name') or ''
            post.title = post.link_title or parsed.netloc or link_url
            post.attachment_paths = []
        else:
            post.link_url = None
            post.link_title = ''
            post.link_description = ''
            post.link_image_url = ''
            post.link_site_name = ''
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
        link_url = validated_data.pop('link_url', None)
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

        target_board = instance.board
        if board_id is not None:
            target_board = Board.objects.filter(id=board_id).first() or target_board

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

        if is_link_share_board(target_board):
            if link_url is not None:
                link_url = _reject_private_or_invalid_url(link_url)
                metadata = fetch_open_graph_metadata(link_url)
                parsed = urlparse(link_url)
                instance.link_url = link_url
                instance.link_title = metadata.get('link_title') or ''
                instance.link_description = metadata.get('link_description') or ''
                instance.link_image_url = metadata.get('link_image_url') or ''
                instance.link_site_name = metadata.get('link_site_name') or ''
                instance.title = instance.link_title or parsed.netloc or link_url
            if not instance.link_url:
                raise serializers.ValidationError({"link_url": "링크 URL을 입력하세요."})
            instance.attachment_paths = []
            validated_data.pop('title', None)
        else:
            instance.link_url = None
            instance.link_title = ''
            instance.link_description = ''
            instance.link_image_url = ''
            instance.link_site_name = ''

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
    link_url = serializers.URLField(read_only=True)
    link_title = serializers.CharField(read_only=True)
    link_description = serializers.CharField(read_only=True)
    link_image_url = serializers.URLField(read_only=True)
    link_site_name = serializers.CharField(read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'board_post_id', 'title', 'content_md', 'user_id', 'author', 'author_semester',
            'created_at', 'updated_at', 'views', 'board', 'comments', 'attachment_paths',
            'likes_count', 'comments_count', 'is_liked', 'post_type', 'is_owner', 'is_anonymous',
            'tag', 'recruitment', 'link_url', 'link_title', 'link_description', 'link_image_url',
            'link_site_name'
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
            return f"{alt_text}({public_media_url(file_key)})"

        pattern = r'(!\[.*?\])\(media-key://(uploads[\\/][^\s\)]+)\)'
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
