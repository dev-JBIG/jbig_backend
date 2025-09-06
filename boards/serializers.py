import bleach
import uuid
import os
from django.core.files.base import ContentFile
from rest_framework import serializers
from .models import Category, Board, Post, Comment, Attachment

class RecursiveField(serializers.Serializer):
    def to_representation(self, value):
        serializer = self.parent.parent.__class__(value, context=self.context)
        return serializer.data

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
            return obj.author == user or user.is_staff
        return False

    def validate_content(self, value):
        # Strip all HTML tags from comments to prevent XSS.
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

class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['id', 'file', 'filename']
        read_only_fields = ('filename',)

class PostListSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)

    class Meta:
        model = Post
        fields = ['id', 'title', 'user_id', 'author', 'author_semester', 'created_at', 'views', 'likes_count']

    def get_user_id(self, obj):
        return obj.author.email.split('@')[0]

class PostCreateUpdateSerializer(serializers.ModelSerializer):
    attachment_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, help_text="첨부파일 ID 목록"
    )
    content_html = serializers.CharField(write_only=True, help_text="게시글 HTML 내용")

    class Meta:
        model = Post
        fields = ['title', 'content_html', 'attachment_ids', 'post_type']

    def _save_html_content(self, instance, html_string):
        # Define allowed tags and attributes for sanitization to prevent XSS attacks
        allowed_tags = [
            'p', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'br', 'blockquote', 'li', 'ol', 'ul',
            'a', 'img', 'pre', 'code', 'span', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td'
        ]
        allowed_attributes = {
            '*': ['class', 'style'],
            'a': ['href', 'title', 'target'],
            'img': ['src', 'alt', 'title', 'style', 'width', 'height'],
        }
        # Sanitize the input HTML
        sanitized_html = bleach.clean(
            html_string,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True  # Strip disallowed tags instead of escaping them
        )

        file_name = f"{uuid.uuid4()}.html"
        instance.content_html.save(file_name, ContentFile(sanitized_html), save=False)

    def create(self, validated_data):
        attachment_ids = validated_data.pop('attachment_ids', [])
        html_content = validated_data.pop('content_html')
        post = Post(**validated_data)
        self._save_html_content(post, html_content)
        post.save()

        # Update search vector after the file is saved.
        post.update_search_vector()
        post.save(update_fields=['search_vector'])

        if attachment_ids:
            post.attachments.set(attachment_ids)
        return post

    def update(self, instance, validated_data):
        attachment_ids = validated_data.pop('attachment_ids', None)
        html_content = validated_data.pop('content_html', None)
        if html_content is not None:
            self._save_html_content(instance, html_content)

        instance = super().update(instance, validated_data)
        
        # Update search vector after content is updated.
        instance.update_search_vector()
        instance.save(update_fields=['search_vector'])

        if attachment_ids is not None:
            instance.attachments.set(attachment_ids)
        return instance

class PostDetailSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    author = serializers.CharField(source='author.username', read_only=True)
    author_semester = serializers.ReadOnlyField(source='author.semester')
    board = BoardSerializer(read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_liked = serializers.SerializerMethodField()
    content_html_url = serializers.URLField(source='content_html.url', read_only=True)
    
    user_can_edit = serializers.SerializerMethodField()
    user_can_delete = serializers.SerializerMethodField()
    user_can_comment = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'content_html_url', 'user_id', 'author', 'author_semester', 'created_at', 'updated_at',
            'views', 'board', 'comments', 'attachments', 'likes_count', 'comments_count', 'is_liked', 'post_type',
            'user_can_edit', 'user_can_delete', 'user_can_comment'
        ]

    def get_user_id(self, obj):
        return obj.author.email.split('@')[0]

    def get_is_liked(self, obj):
        user = self.context['request'].user
        return user.is_authenticated and obj.likes.filter(pk=user.pk).exists()

    def get_user_can_edit(self, obj):
        user = self.context['request'].user
        return user.is_authenticated and (obj.author == user or user.is_staff)

    def get_user_can_delete(self, obj):
        user = self.context['request'].user
        return user.is_authenticated and (obj.author == user or user.is_staff)

    def get_user_can_comment(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        perm = getattr(obj.board, 'comment_permission', 'staff')
        if perm == 'all':
            return True
        return user.is_staff

class PostDetailResponseSerializer(serializers.Serializer):
    post = PostDetailSerializer()
    # Removed permissions field as it's now in PostDetailSerializer

class PostListResponseSerializer(serializers.Serializer):
    board = BoardSerializer()
    posts = PostListSerializer(many=True)
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)

class CategoryListResponseSerializer(serializers.Serializer):
    total_post_count = serializers.IntegerField()
    categories = CategoryWithBoardsSerializer(many=True)


