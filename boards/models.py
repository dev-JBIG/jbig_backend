from django.db import models
from django.conf import settings
from django.db.models import Q
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from bs4 import BeautifulSoup


# DB 스키마 마이그레이션 완료 (2025-10-26):
# Post.content_html -> Post.content_md (Markdown 텍스트 저장)
# Attachment FK -> Post.attachment_paths (JSON 매핑)


# [Deprecated] 마이그레이션 호환성을 위해 유지 - 실제로 사용되지 않음
def post_upload_path(instance, filename):
    return f'boards/{instance.board.id}/{filename}'


class Category(models.Model):
    name = models.CharField(max_length=50)

    class Meta:
        db_table = 'category'
        verbose_name = '게시판 카테고리'
        verbose_name_plural = '게시판 카테고리 목록'

    def __str__(self):
        return self.name


class Board(models.Model):
    class BoardType(models.IntegerChoices):
        GENERAL = 1, 'General'
        ADMIN = 2, 'Admin'
        JUSTIFICATION_LETTER = 3, 'Justification Letter'

    name = models.CharField(max_length=50)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='boards')
    board_type = models.IntegerField(choices=BoardType.choices, default=BoardType.GENERAL)

    PERMISSION_CHOICES = (
        ('all', 'All'),
        ('staff', 'Staff'),
    )
    read_permission = models.CharField(max_length=10, choices=PERMISSION_CHOICES, default='all')
    post_permission = models.CharField(max_length=10, choices=PERMISSION_CHOICES, default='all')
    comment_permission = models.CharField(max_length=10, choices=PERMISSION_CHOICES, default='all')

    class Meta:
        db_table = 'board'
        verbose_name = '게시판'
        verbose_name_plural = '게시판 목록'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.board_type == self.BoardType.ADMIN:
            self.read_permission = 'all'
            self.post_permission = 'staff'
            self.comment_permission = 'all'
        elif self.board_type == self.BoardType.GENERAL:
            self.read_permission = 'all'
            self.post_permission = 'all'
            self.comment_permission = 'all'
        elif self.board_type == self.BoardType.JUSTIFICATION_LETTER:
            self.read_permission = 'all'
            self.post_permission = 'all'
            self.comment_permission = 'staff'
        super().save(*args, **kwargs)


class PostQuerySet(models.QuerySet):
    def visible_for_user(self, user):
        if user.is_authenticated and user.is_staff:
            return self
        
        # TODO: 추후 프론트엔드에 기능 구현 시 아래 주석 해제하여 활성화
        # # Exclude staff-only posts for non-staff
        # queryset = self.exclude(post_type=Post.PostType.STAFF_ONLY)

        # 현재는 STAFF_ONLY 글도 일반 글처럼 취급
        queryset = self

        if user.is_authenticated:
            # Authenticated non-staff can see default/staff_only posts and their own justification letters
            queryset = queryset.filter(
                Q(post_type=Post.PostType.DEFAULT) |
                Q(post_type=Post.PostType.STAFF_ONLY) | # STAFF_ONLY 글도 목록에 포함
                Q(post_type=Post.PostType.JUSTIFICATION_LETTER, author__id=user.id)
            )
        else:
            # Anonymous users can only see default/staff_only posts
            queryset = queryset.filter(
                Q(post_type=Post.PostType.DEFAULT) |
                Q(post_type=Post.PostType.STAFF_ONLY) # STAFF_ONLY 글도 목록에 포함
            )
            
        return queryset

class PostManager(models.Manager):
    def get_queryset(self):
        return PostQuerySet(self.model, using=self._db)

    def visible_for_user(self, user):
        return self.get_queryset().visible_for_user(user)


class Post(models.Model):
    class PostType(models.IntegerChoices):
        DEFAULT = 1, 'Default'
        STAFF_ONLY = 2, 'Staff Only'
        JUSTIFICATION_LETTER = 3, 'Justification Letter'

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='posts')
    title = models.CharField(max_length=200)
    content_md = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    views = models.PositiveIntegerField(default=0)
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='liked_posts',
        blank=True,
        through='PostLike'
    )
    post_type = models.IntegerField(choices=PostType.choices, default=PostType.DEFAULT)
    search_vector = SearchVectorField(null=True, editable=False)
    board_post_id = models.IntegerField(null=True, blank=True)
    attachment_paths = models.JSONField(default=list, blank=True, help_text="첨부파일 경로 목록")

    objects = PostManager()

    class Meta:
        db_table = 'post'
        verbose_name = '게시글'
        verbose_name_plural = '게시글 목록'
        indexes = [
            GinIndex(fields=['search_vector']),
        ]
        unique_together = ('board', 'board_post_id')

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.board_post_id:
            max_id = Post.objects.filter(board=self.board).aggregate(models.Max('board_post_id'))['board_post_id__max']
            self.board_post_id = (max_id or 0) + 1
        super().save(*args, **kwargs)

    def update_search_vector(self):
        content_text = ''

        if self.content_md: # 이제 파일이 아닌 텍스트 문자열이므로 .path 등이 필요 없습니다.
            try:
                # 파일(f)을 여는 대신, 마크다운 문자열(self.content_md)을 직접 파싱합니다.
                soup = BeautifulSoup(self.content_md, 'html.parser')
                content_text = soup.get_text()
            except Exception:
                content_text = '' # In case of error, proceed with empty content
        
        # We use 'config='ko'' if a Korean stemmer is installed in PostgreSQL.
        # Otherwise, use the default.
        self.search_vector = SearchVector('title', weight='A') + SearchVector(models.Value(content_text), weight='B')

    


class PostLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'post_like'
        unique_together = ('user', 'post')

class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField()
    parent = models.ForeignKey(
        'self', null=True, blank=True, related_name='children', on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'comment'
        verbose_name = '댓글'
        verbose_name_plural = '댓글 목록'

    def __str__(self):
        return f'Comment by {self.author} on {self.post}'

# [Deprecated] 레거시 모델 - 첨부파일은 이제 NCP Object Storage + Post.attachment_paths JSON 필드 사용
# DB 스키마 호환성을 위해 유지하지만, 새 첨부파일에는 사용되지 않음
class Attachment(models.Model):
    file = models.FileField(upload_to='attachments/')
    filename = models.CharField(max_length=255)

    class Meta:
        db_table = 'attachment'
        verbose_name = '[Deprecated] 첨부파일'
        verbose_name_plural = '[Deprecated] 첨부파일 목록'

    def __str__(self):
        return self.filename
