from rest_framework import serializers
import bleach
from django.db.models import Prefetch
from .models import Category, Board, Post, Comment, Attachment

# NCP 연동 위해 추가
import boto3
import os
import re
from django.conf import settings
from botocore.client import Config
from botocore.exceptions import ClientError
import logging
logger = logging.getLogger(__name__)




class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']


class BoardSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    read_permission = serializers.SerializerMethodField()
    post_permission = serializers.SerializerMethodField()
    comment_permission = serializers.SerializerMethodField()

    class Meta:
        model = Board
        fields = ['id', 'name', 'category', 'read_permission', 'post_permission', 'comment_permission']

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
        fields = ['id', 'name']

class CategoryWithBoardsSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source='name')
    boards = BoardIdNameSerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ['category', 'boards']

class CommentSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    children = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    post_id = serializers.IntegerField(source='post.id', read_only=True)
    post_title = serializers.CharField(source='post.title', read_only=True)
    board_id = serializers.IntegerField(source='post.board.id', read_only=True)
    parent = serializers.IntegerField(source='parent_id', read_only=True)

    class Meta:
        model = Comment
        fields = [
            'id', 'post_id', 'post_title', 'user_id', 'author', 'author_semester',
            'content', 'created_at', 'parent', 'children', 'is_owner', 'is_deleted',
            'board_id'
        ]
        read_only_fields = (
            'user_id', 'author', 'author_semester', 'created_at', 'children',
            'is_owner', 'is_deleted', 'post_id', 'post_title', 'board_id', 'parent'
        )

    def get_user_id(self, obj):
        if obj.author:
            return obj.author.email.split('@')[0]
        return '알 수 없는 사용자'

    def get_is_owner(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.author == user
        return False

    def get_children(self, obj):
        child_qs = obj.children.all().order_by('created_at')
        if not child_qs.exists():
            return []
        serializer = CommentSerializer(child_qs, many=True, context=self.context)
        return serializer.data

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if instance.is_deleted:
            representation['content'] = '삭제된 댓글입니다.'
            representation['author'] = '알 수 없는 사용자'
            representation['user_id'] = '알 수 없는 사용자'
        return representation


class CommentWriteSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Comment.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = Comment
        fields = ['id', 'content', 'parent']
        read_only_fields = ['id']

    def _strip_leading_quote_block(self, text: str) -> str:
        lines = text.splitlines()
        cleaned_lines = []
        stripping = True

        for line in lines:
            normalized = line.lstrip()

            if stripping:
                if not normalized:
                    continue
                if normalized.startswith('>'):
                    continue
                if normalized.startswith('답변:') or normalized.startswith('답변 '):
                    continue
                stripping = False

            cleaned_lines.append(line)

        if not cleaned_lines:
            return text
        return '\n'.join(cleaned_lines).strip()

    def to_internal_value(self, data):
        mutable_data = data.copy()
        current_parent = mutable_data.get('parent')

        if current_parent in ('', None):
            mutable_data['parent'] = None

        if 'parent' not in mutable_data or mutable_data.get('parent') is None:
            parent_alias = mutable_data.get('parentId') or mutable_data.get('parent_id')
            if parent_alias is not None:
                mutable_data['parent'] = parent_alias

        return super().to_internal_value(mutable_data)

    def validate_parent(self, parent):
        if parent is None:
            return None

        post = self.context.get('post')
        if not post and self.instance:
            post = self.instance.post

        if not post:
            raise serializers.ValidationError("게시글 정보가 필요합니다.")

        if parent.post_id != post.id:
            raise serializers.ValidationError("Parent comment does not belong to this post.")

        if parent.parent_id is not None:
            raise serializers.ValidationError("대댓글에는 다시 답글을 달 수 없습니다.")

        return parent

    def validate_content(self, value):
        sanitized_content = bleach.clean(value, tags=[], strip=True).strip()
        if not sanitized_content:
            raise serializers.ValidationError("Content cannot be empty.")

        stripped_content = self._strip_leading_quote_block(sanitized_content)
        if not stripped_content:
            raise serializers.ValidationError("Content cannot be empty.")

        return stripped_content

class AttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Attachment
        fields = ['id', 'file', 'filename', 'file_url']
        read_only_fields = ('filename', 'file_url')
    
    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None

class PostListSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
   # attachment_paths = serializers.JSONField(read_only=True, help_text="첨부파일 정보 목록 (url, name 포함)")
    attachment_paths = serializers.SerializerMethodField(help_text="첨부파일 정보 목록 (실시간 생성된 다운로드 URL 포함)")


    class Meta:
        model = Post
        fields = ['id', 'board_post_id', 'title', 'user_id', 'author', 'author_semester', 'created_at', 'views', 'likes_count', 'attachment_paths']

    def get_user_id(self, obj):
        return obj.author.email.split('@')[0]
   

    # NCP 위해 메소드 추가
    # PostListSerializer의 get_attachment_paths 함수
    def get_attachment_paths(self, obj):
        attachments_list = obj.attachment_paths
        if not attachments_list or not isinstance(attachments_list, list):
            return []

        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.NCP_ENDPOINT_URL,
                aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                aws_secret_access_key=settings.NCP_SECRET_KEY,
                config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
            )
        except Exception as e:
            logger.error(f"S3 클라이언트 생성 실패 (Serializer): {e}")
            return []

        presigned_attachments = []
        for item in attachments_list:
            file_key_or_url = item.get('path') or item.get('url')
            original_name = item.get('name')

            if not file_key_or_url or not original_name:
                continue

            download_url = ""
            file_size = None # 파일 크기를 담을 변수

            try:
                # 'uploads/'로 시작하면 '새 형식' (NCP)
                if file_key_or_url.startswith("uploads/"):
                    # 1. NCP에서 파일 크기(head_object) 가져오기
                    meta = s3_client.head_object(
                        Bucket=settings.NCP_BUCKET_NAME,
                        Key=file_key_or_url
                    )
                    file_size = meta.get('ContentLength')

                    # 2. 다운로드용 Presigned URL 발급
                    download_url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={
                            'Bucket': settings.NCP_BUCKET_NAME,
                            'Key': file_key_or_url,
                        }
                       #  ExpiresIn=3600 # 1시간
                    )

                # 그 외에는 '옛날 형식' (/media/...)
                else: 
                    download_url = file_key_or_url
                    # 1. Django 서버 로컬에서 파일 크기 가져오기
                    try:
                        # /media/attachments/file.pdf -> /home/ubuntu/jbig-project/jbig_backend/media/attachments/file.pdf
                        local_path = os.path.join(settings.MEDIA_ROOT, file_key_or_url.lstrip('/'))
                        if os.path.exists(local_path):
                            file_size = os.path.getsize(local_path)
                    except Exception as e:
                        logger.warn(f"옛날 파일 크기 조회 실패 ({file_key_or_url}): {e}")

                presigned_attachments.append({
                    "url": download_url,
                    "name": original_name,
                    "size": file_size  # <-- 파일 크기 정보 추가
                })

            except ClientError as e:
                logger.error(f"S3 처리 중 에러 (Key: {file_key_or_url}): {e}")
                continue # 실패 시 이 파일은 건너뜀

        return presigned_attachments





class PostCreateUpdateSerializer(serializers.ModelSerializer):
    attachment_paths = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False, help_text="첨부파일 정보 목록 (url, name 포함)"
    )
    content_md = serializers.CharField(write_only=True, help_text="게시글 마크다운 내용")

    class Meta:
        model = Post
        fields = ['title', 'content_md', 'attachment_paths', 'post_type']


    def create(self, validated_data):
        attachment_paths = validated_data.pop('attachment_paths', [])
        content_md = validated_data.pop('content_md')
        post = Post(**validated_data)
        post.content_md = content_md
        post.attachment_paths = attachment_paths
        post.save()

        # Update search vector after the file is saved.
        post.update_search_vector()
        post.save(update_fields=['search_vector'])
        return post

    def update(self, instance, validated_data):
        attachment_paths = validated_data.pop('attachment_paths', None)
        content_md = validated_data.pop('content_md', None)
        
        if content_md is not None:
            instance.content_md = content_md
        
        if attachment_paths is not None:
            instance.attachment_paths = attachment_paths
            
        instance = super().update(instance, validated_data)
        
        # Update search vector after content is updated.
        instance.update_search_vector()
        instance.save(update_fields=['search_vector'])
        return instance

class PostDetailSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    board = BoardSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
   # attachment_paths = serializers.JSONField(read_only=True, help_text="첨부파일 정보 목록 (url, name 포함)")
    attachment_paths = serializers.SerializerMethodField(help_text="첨부파일 정보 목록 (실시간 생성된 다운로드 URL 포함)")
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_liked = serializers.SerializerMethodField()

   # content_md = serializers.CharField(read_only=True)
    
    content_md = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    
    # user_can_edit = serializers.SerializerMethodField()
    # user_can_delete = serializers.SerializerMethodField()
    # user_can_comment = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'board_post_id', 'title', 'content_md', 'user_id', 'author', 'author_semester', 'created_at', 'updated_at',
            'views', 'board', 'comments', 'attachment_paths', 'likes_count', 'comments_count', 'is_liked', 'post_type', 'is_owner'
            # 'user_can_edit', 'user_can_delete', 'user_can_comment'

        ]

    def get_user_id(self, obj):
        return obj.author.email.split('@')[0]

    def get_is_liked(self, obj):
        user = self.context['request'].user
        return user.is_authenticated and obj.likes.filter(pk=user.pk).exists()

    def get_is_owner(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.author == user
        return False

    def get_comments(self, obj):
        """
        대댓글이 최상위 comments 배열에 중복 노출되지 않도록
        parent 가 없는 댓글만 직렬화한다.
        """
        top_level_qs = (
            obj.comments
            .filter(parent__isnull=True)
            .order_by('created_at')
            .prefetch_related('children')
        )
        serializer = CommentSerializer(
            top_level_qs,
            many=True,
            context=self.context,
        )
        return serializer.data







# ... (get_is_owner 함수 다음, 같은 들여쓰기 레벨)

    # NCP 위해 메소드 추가
    def get_content_md(self, obj):
        """
        DB에 저장된 content_md에서 'ncp-key://...' 태그를 찾아
        실시간으로 다운로드용 Presigned URL로 변환합니다.
        """
        raw_md = obj.content_md
        if not raw_md:
            return ""

        # S3 클라이언트 한 번만 생성 (실패 시 원본 반환)
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.NCP_ENDPOINT_URL,
                aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                aws_secret_access_key=settings.NCP_SECRET_KEY,
                config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
            )
        except Exception:
            return raw_md 

        # 'ncp-key://(파일경로)' 패턴을 찾는 함수
        def replace_with_presigned_url(match):
            # match.group(1)은 (ncp-key://...) 전체
            # match.group(2)는 ( ) 안의 ncp-key://...
           # file_key = match.group(3) # 세 번째 ( ) 안의 파일 경로(Key)
            file_key = match.group(4) 
  
            if not file_key:
                return match.group(0) # 매치 실패 시 원본 문자열 반환 (예: "![alt](url)")

            try:
                # 1시간짜리 새 URL 발급
                download_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': settings.NCP_BUCKET_NAME, 'Key': file_key}
                   #  ExpiresIn=3600
                )
                # () 괄호와 URL 전체를 교체
                return f"({download_url})" 
            except Exception:
                return match.group(0) # URL 발급 실패 시 원본 문자열 반환

        # 정규표현식을 사용해 모든 "](ncp-key://...)"를 찾아 'replace_with_presigned_url' 함수로 처리
        # 예: ![alt](ncp-key://uploads/...) -> ![alt](https://...Signature=...)
        processed_md = re.sub(
            r"(\!\[[^\]]*\])(\((ncp-key:\/\/([^\)]+))\))", # ![alt](ncp-key://경로)
            lambda m: m.group(1) + replace_with_presigned_url(m), # alt 부분(group 1)은 놔두고 URL 부분(group 2)만 교체
            raw_md
        )

        return processed_md





    # NCP 위해 메소드 추가
    def get_attachment_paths(self, obj):
        attachments_list = obj.attachment_paths
        if not attachments_list or not isinstance(attachments_list, list):
            return []

        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.NCP_ENDPOINT_URL,
                aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                aws_secret_access_key=settings.NCP_SECRET_KEY,
                config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
            )
        except Exception as e:
            logger.error(f"S3 클라이언트 생성 실패 (Serializer): {e}")
            return []

        presigned_attachments = []
        for item in attachments_list:
            file_key_or_url = item.get('path') or item.get('url')
            original_name = item.get('name')

            if not file_key_or_url or not original_name:
                continue

            download_url = ""
            file_size = None # 파일 크기를 담을 변수

            try:
                # 'uploads/'로 시작하면 '새 형식' (NCP)
                if file_key_or_url.startswith("uploads/"):
                    # 1. NCP에서 파일 크기(head_object) 가져오기
                    meta = s3_client.head_object(
                        Bucket=settings.NCP_BUCKET_NAME,
                        Key=file_key_or_url
                    )
                    file_size = meta.get('ContentLength')

                    # 2. 다운로드용 Presigned URL 발급
                    download_url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={
                            'Bucket': settings.NCP_BUCKET_NAME,
                            'Key': file_key_or_url,
                        }
                      #  ExpiresIn=3600 # 1시간
                    )

                # 그 외에는 '옛날 형식' (/media/...)
                else: 
                    download_url = file_key_or_url
                    # 1. Django 서버 로컬에서 파일 크기 가져오기
                    try:
                        # /media/attachments/file.pdf -> /home/ubuntu/jbig-project/jbig_backend/media/attachments/file.pdf
                        local_path = os.path.join(settings.MEDIA_ROOT, file_key_or_url.lstrip('/'))
                        if os.path.exists(local_path):
                            file_size = os.path.getsize(local_path)
                    except Exception as e:
                        logger.warn(f"옛날 파일 크기 조회 실패 ({file_key_or_url}): {e}")

                presigned_attachments.append({
                    "url": download_url,
                    "name": original_name,
                    "size": file_size  # <-- 파일 크기 정보 추가
                })

            except ClientError as e:
                logger.error(f"S3 처리 중 에러 (Key: {file_key_or_url}): {e}")
                continue # 실패 시 이 파일은 건너뜀

        return presigned_attachments

    # def get_user_can_edit(self, obj):
    #     user = self.context['request'].user
    #     return user.is_authenticated and obj.author.id == user.id

    # def get_user_can_delete(self, obj):
    #     user = self.context['request'].user
    #     return user.is_authenticated and obj.author.id == user.id

    # def get_user_can_comment(self, obj):
    #     user = self.context['request'].user
    #     if not user.is_authenticated:
    #         return False
    #     perm = getattr(obj.board, 'comment_permission', 'staff')
    #     if perm == 'all':
    #         return True
    #     return user.is_staff



class PostListResponseSerializer(serializers.Serializer):
    board = BoardSerializer()
    posts = PostListSerializer(many=True)
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)

class CategoryListResponseSerializer(serializers.Serializer):
    total_post_count = serializers.IntegerField()
    categories = CategoryWithBoardsSerializer(many=True)
