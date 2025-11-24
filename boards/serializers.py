import re
import logging

import boto3
import bleach
from botocore.client import Config
from botocore.exceptions import ClientError

from django.conf import settings
from rest_framework import serializers

from .models import Category, Board, Post, Comment

logger = logging.getLogger(__name__)

_s3_client = None

def get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            's3',
            endpoint_url=settings.NCP_ENDPOINT_URL,
            aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
            aws_secret_access_key=settings.NCP_SECRET_KEY,
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
        )
    return _s3_client


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
    children = RecursiveField(many=True, read_only=True)
    is_owner = serializers.SerializerMethodField()
    post_id = serializers.IntegerField(source='post.id', read_only=True)
    post_title = serializers.CharField(source='post.title', read_only=True)
    board_id = serializers.IntegerField(source='post.board.id', read_only=True)

    class Meta:
        model = Comment
        fields = ['id', 'post_id', 'post_title', 'user_id', 'author', 'author_semester', 'content', 'created_at', 'parent', 'children', 'is_owner', 'is_deleted', 'board_id']
        read_only_fields = ('user_id', 'author', 'author_semester', 'created_at', 'children', 'is_owner', 'is_deleted', 'post_id', 'post_title', 'board_id')


    def get_user_id(self, obj):
        if obj.author:
            return obj.author.email.split('@')[0]
        return '알 수 없는 사용자'

    def get_is_owner(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            return obj.author == user
        return False

    def validate_content(self, value):
        sanitized_content = bleach.clean(value, tags=[], strip=True).strip()
        if not sanitized_content:
            raise serializers.ValidationError("Content cannot be empty.")
        return sanitized_content

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if instance.is_deleted:
            representation['content'] = '삭제된 댓글입니다.'
            representation['author'] = '알 수 없는 사용자'
            representation['user_id'] = '알 수 없는 사용자'
        return representation

class PostListSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    attachment_paths = serializers.SerializerMethodField()


    class Meta:
        model = Post
        fields = ['id', 'board_post_id', 'title', 'user_id', 'author', 'author_semester', 'created_at', 'views', 'likes_count', 'attachment_paths']

    def get_user_id(self, obj):
        return obj.author.email.split('@')[0]

    def get_attachment_paths(self, obj):
        attachments_list = obj.attachment_paths
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


def normalize_ncp_urls(content):
    """NCP presigned URL을 ncp-key:// 형식으로 정규화"""
    if not content:
        return content
    pattern = r'https://kr\.object\.ncloudstorage\.com/jbig/(uploads/[^?\s\)]+)(?:\?[^\s\)]*)?'
    return re.sub(pattern, r'ncp-key://\1', content)


class PostCreateUpdateSerializer(serializers.ModelSerializer):
    attachment_paths = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    content_md = serializers.CharField(write_only=True)

    class Meta:
        model = Post
        fields = ['title', 'content_md', 'attachment_paths', 'post_type']


    def create(self, validated_data):
        attachment_paths = validated_data.pop('attachment_paths', [])
        content_md = validated_data.pop('content_md')
        post = Post(**validated_data)
        post.content_md = normalize_ncp_urls(content_md)
        post.attachment_paths = attachment_paths
        post.save()
        post.update_search_vector()
        post.save(update_fields=['search_vector'])
        return post

    def update(self, instance, validated_data):
        attachment_paths = validated_data.pop('attachment_paths', None)
        content_md = validated_data.pop('content_md', None)

        if content_md is not None:
            instance.content_md = normalize_ncp_urls(content_md)
        
        if attachment_paths is not None:
            instance.attachment_paths = attachment_paths
            
        instance = super().update(instance, validated_data)
        instance.update_search_vector()
        instance.save(update_fields=['search_vector'])
        return instance

class PostDetailSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    board = BoardSerializer(read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    attachment_paths = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_liked = serializers.SerializerMethodField()
    content_md = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'board_post_id', 'title', 'content_md', 'user_id', 'author', 'author_semester',
            'created_at', 'updated_at', 'views', 'board', 'comments', 'attachment_paths',
            'likes_count', 'comments_count', 'is_liked', 'post_type', 'is_owner'
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

    def get_content_md(self, obj):
        raw_md = obj.content_md
        if not raw_md:
            return ""
        try:
            s3_client = get_s3_client()
        except Exception:
            return raw_md

        def replace_with_presigned_url(match):
            file_key = match.group(4)
            if not file_key:
                return match.group(0)
            try:
                url = s3_client.generate_presigned_url('get_object', Params={'Bucket': settings.NCP_BUCKET_NAME, 'Key': file_key}, ExpiresIn=3600)
                return f"({url})"
            except Exception:
                return match.group(0)

        return re.sub(r"(\!\[[^\]]*\])(\((ncp-key:\/\/([^\)]+))\))", lambda m: m.group(1) + replace_with_presigned_url(m), raw_md)

    def get_attachment_paths(self, obj):
        attachments_list = obj.attachment_paths
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


class PostListResponseSerializer(serializers.Serializer):
    board = BoardSerializer()
    posts = PostListSerializer(many=True)
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)

class CategoryListResponseSerializer(serializers.Serializer):
    total_post_count = serializers.IntegerField()
    categories = CategoryWithBoardsSerializer(many=True)
