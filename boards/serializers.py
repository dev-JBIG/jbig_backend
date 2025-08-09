import bleach
import uuid
from django.core.files.base import ContentFile
from rest_framework import serializers
from .models import Category, Board, Post, Comment, Attachment

# Bleach를 사용하여 허용할 HTML 태그 및 속성 정의
ALLOWED_TAGS = [
    'p', 'b', 'i', 'u', 's', 'strike', 'strong', 'em', 'span', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote',
    'a', 'img', 'pre', 'code', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
]
ALLOWED_ATTRIBUTES = {
    '*': ['style', 'class'],
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
}


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

    class Meta:
        model = Board
        fields = ['id', 'name', 'category']

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
    author = serializers.CharField(source='author.username', read_only=True)
    children = RecursiveField(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = ['id', 'author', 'content', 'created_at', 'parent', 'children']
        read_only_fields = ('author', 'created_at', 'children')


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['id', 'file', 'filename']
        read_only_fields = ('filename',)


class PostListSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source='author.username', read_only=True)
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)

    class Meta:
        model = Post
        fields = ['id', 'title', 'author', 'created_at', 'views', 'likes_count']


class PostCreateUpdateSerializer(serializers.ModelSerializer):
    attachment_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="첨부파일 ID 목록"
    )
    content_html = serializers.CharField(write_only=True, help_text="게시글 HTML 내용")

    class Meta:
        model = Post
        fields = ['title', 'content_html', 'attachment_ids']

    def _save_html_content(self, instance, html_string):
        """HTML 문자열을 소독하고 파일로 저장 또는 덮어씁니다."""
        sanitized_html = bleach.clean(html_string, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
        
        # 수정이고 기존 파일이 있는 경우, 해당 파일에 덮어쓰기
        if instance.pk and instance.content_html and instance.content_html.name:
            file_name = os.path.basename(instance.content_html.name)
        else:
            # 생성의 경우, 새 UUID로 파일 이름 생성
            file_name = f"{uuid.uuid4()}.html"
            
        instance.content_html.save(file_name, ContentFile(sanitized_html), save=False)

    def validate(self, data):
        attachment_ids = data.get('attachment_ids', [])

        # 파일 개수 검증
        if len(attachment_ids) > 3:
            raise serializers.ValidationError("최대 3개의 파일만 첨부할 수 있습니다.")

        # 총 용량 검증
        attachments = Attachment.objects.filter(id__in=attachment_ids)
        total_size = sum(att.file.size for att in attachments)
        if total_size > 20 * 1024 * 1024:  # 20MB
            raise serializers.ValidationError("첨부파일의 총 용량은 20MB를 초과할 수 없습니다.")
        
        # 모든 attachment_ids가 유효한지 확인
        if len(attachment_ids) != attachments.count():
            raise serializers.ValidationError("존재하지 않는 첨부파일 ID가 포함되어 있습니다.")

        return data

    def create(self, validated_data):
        attachment_ids = validated_data.pop('attachment_ids', [])
        html_content = validated_data.pop('content_html')
        
        # Post 인스턴스는 생성하지만 아직 DB에 저장하지 않음
        post = Post(**validated_data)
        
        # HTML 내용을 파일로 만들어 Post 인스턴스에 연결
        self._save_html_content(post, html_content)
        
        # 모든 필드가 준비된 후 Post 저장
        post.save()

        # 첨부파일 연결
        if attachment_ids:
            attachments = Attachment.objects.filter(id__in=attachment_ids)
            post.attachments.set(attachments)
        return post

    def update(self, instance, validated_data):
        attachment_ids = validated_data.pop('attachment_ids', None)
        html_content = validated_data.pop('content_html', None)

        # HTML 내용이 있으면 파일 덮어쓰기
        if html_content is not None:
            self._save_html_content(instance, html_content)

        # 나머지 필드 업데이트
        # super().update()는 save()를 호출하므로, HTML 파일 처리 후에 호출
        instance = super().update(instance, validated_data)

        # 첨부파일 연결
        if attachment_ids is not None:
            attachments = Attachment.objects.filter(id__in=attachment_ids)
            instance.attachments.set(attachments)
            
        return instance


class PostDetailSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source='author.username', read_only=True)
    board = BoardSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    is_liked = serializers.SerializerMethodField()
    content_html_url = serializers.URLField(source='content_html.url', read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'content_html_url', 'author', 'created_at', 'updated_at',
            'views', 'board', 'comments', 'attachments', 'likes_count', 'is_liked'
        ]

    def get_comments(self, obj):
        top_level_comments = obj.comments.filter(parent__isnull=True)
        serializer = CommentSerializer(top_level_comments, many=True, context=self.context)
        return serializer.data

    def get_is_liked(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            return obj.likes.filter(pk=user.pk).exists()
        return False


class PostDetailResponseSerializer(serializers.Serializer):
    """Serializer for the response of the post detail view."""
    post_data = PostDetailSerializer()
    isTokenValid = serializers.BooleanField()
    isAdmin = serializers.BooleanField()
    username = serializers.CharField()
    email = serializers.EmailField()


class CategoryListResponseSerializer(serializers.Serializer):
    total_post_count = serializers.IntegerField()
    categories = CategoryWithBoardsSerializer(many=True)