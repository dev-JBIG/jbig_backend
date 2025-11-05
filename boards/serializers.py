from rest_framework import serializers
import bleach
from .models import Category, Board, Post, Comment, Attachment



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
   # children = serializers.ListSerializer(child=serializers.CharField(), read_only=True)



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
    attachment_paths = serializers.JSONField(read_only=True, help_text="첨부파일 정보 목록 (url, name 포함)")

    class Meta:
        model = Post
        fields = ['id', 'board_post_id', 'title', 'user_id', 'author', 'author_semester', 'created_at', 'views', 'likes_count', 'attachment_paths']

    def get_user_id(self, obj):
        return obj.author.email.split('@')[0]

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
    comments = CommentSerializer(many=True, read_only=True)
    attachment_paths = serializers.JSONField(read_only=True, help_text="첨부파일 정보 목록 (url, name 포함)")
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_liked = serializers.SerializerMethodField()

    content_md = serializers.CharField(read_only=True)

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
