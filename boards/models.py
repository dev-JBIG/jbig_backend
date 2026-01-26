from django.db import models
from django.conf import settings
from django.db.models import Q
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from bs4 import BeautifulSoup
import random
import hashlib


def post_upload_path(instance, filename):
    """Deprecated - 마이그레이션 호환성 위해 유지"""
    return f'boards/{instance.board.id}/{filename}'


# 무작위 닉네임 생성을 위한 단어 리스트
ADJECTIVES = [
    '딱딱한', '부드러운', '상냥한', '날카로운', '따뜻한', '차가운', '빠른', '느린',
    '밝은', '어두운', '큰', '작은', '높은', '낮은', '깊은', '얕은', '넓은', '좁은',
    '강한', '약한', '단단한', '무른', '매운', '달콤한', '쓴', '시원한', '뜨거운',
    '차분한', '활발한', '조용한', '시끄러운', '편안한', '불편한', '깨끗한', '지저분한',
    '예쁜', '못생긴', '귀여운', '무서운', '친절한', '무뚝뚝한', '재미있는', '지루한',
    '신나는', '우울한', '행복한', '슬픈', '화난', '평화로운', '바쁜', '한가한'
]

NOUNS = [
    '두쫀쿠', '밤티', '샤갈', '호날두', '오봉', '표돌이', '표순이', '두쫀붕',
    '슈붕', '팥붕', '조림핑', '전붕이', '전순이', '오퍼스', '소넷',
    '하이쿠', '제미니', 'GPT', '올트먼', '머스크', '마라탕', '마라샹궈',
    '코다리', '고양이', '햄스터', '쿼카', '팬케이크', '오믈렛', '아기맹수', '비빔대왕'
]


def generate_anonymous_nickname(user_id, post_id, semester=None):
    """
    사용자 ID와 게시글 ID를 조합하여 일관된 무작위 닉네임 생성
    같은 게시글 내에서 같은 사용자는 항상 동일한 닉네임을 가짐
    semester가 있으면 "N기 명사", 없으면 "형용사 명사" 형식으로 생성됨
    """
    # 해시를 사용하여 동일한 입력에 대해 항상 같은 닉네임 생성
    seed_string = f"{user_id}_{post_id}"
    hash_value = int(hashlib.sha256(seed_string.encode()).hexdigest(), 16)
    
    # 해시값을 사용하여 형용사와 명사 선택
    adj_index = hash_value % len(ADJECTIVES)
    noun_index = (hash_value // len(ADJECTIVES)) % len(NOUNS)
    
    # semester가 있으면 "N기", 없으면 형용사 사용
    if semester:
        prefix = f"{semester}기"
    else:
        prefix = ADJECTIVES[adj_index]
    
    return f"{prefix} {NOUNS[noun_index]}"


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
        
        queryset = self

        if user.is_authenticated:
            queryset = queryset.filter(
                Q(post_type=Post.PostType.DEFAULT) |
                Q(post_type=Post.PostType.STAFF_ONLY) |
                Q(post_type=Post.PostType.JUSTIFICATION_LETTER, author__id=user.id)
            )
        else:
            queryset = queryset.filter(
                Q(post_type=Post.PostType.DEFAULT) |
                Q(post_type=Post.PostType.STAFF_ONLY)
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
    is_anonymous = models.BooleanField(default=False, help_text="익명 작성 여부")

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
        if self.content_md:
            try:
                soup = BeautifulSoup(self.content_md, 'html.parser')
                content_text = soup.get_text()
            except Exception:
                content_text = ''
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
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, through='CommentLike', related_name='liked_comments')
    is_anonymous = models.BooleanField(default=False, help_text="익명 작성 여부")

    class Meta:
        db_table = 'comment'
        verbose_name = '댓글'
        verbose_name_plural = '댓글 목록'

    def __str__(self):
        return f'Comment by {self.author} on {self.post}'

class CommentLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comment_like'
        unique_together = ('user', 'comment')

class Attachment(models.Model):
    """Deprecated - DB 호환성 위해 유지"""
    file = models.FileField(upload_to='attachments/')
    filename = models.CharField(max_length=255)

    class Meta:
        db_table = 'attachment'
        verbose_name = '[Deprecated] 첨부파일'
        verbose_name_plural = '[Deprecated] 첨부파일'

    def __str__(self):
        return self.filename


class Notification(models.Model):
    class NotificationType(models.IntegerChoices):
        COMMENT = 1, '댓글'           # 내 글에 댓글이 달림
        REPLY = 2, '대댓글'            # 내 댓글에 대댓글이 달림
        LIKE = 3, '좋아요'             # 내 글에 좋아요가 달림
        COMMENT_LIKE = 4, '댓글 좋아요'  # 내 댓글에 좋아요가 달림

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='알림 받는 사용자'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications_sent',
        verbose_name='알림 발생시킨 사용자'
    )
    notification_type = models.IntegerField(
        choices=NotificationType.choices,
        verbose_name='알림 유형'
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='관련 게시글'
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='관련 댓글'
    )
    is_read = models.BooleanField(default=False, verbose_name='읽음 여부')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification'
        verbose_name = '알림'
        verbose_name_plural = '알림 목록'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.recipient}에게 {self.get_notification_type_display()} 알림'


class Draft(models.Model):
    """게시글 작성 버퍼 - 사용자당 하나의 임시저장 슬롯"""
    author = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='draft_buffer',
        verbose_name='작성자',
        primary_key=True
    )
    board = models.ForeignKey(
        Board,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drafts',
        verbose_name='게시판'
    )
    title = models.CharField(max_length=200, blank=True, verbose_name='제목')
    content_md = models.TextField(blank=True, verbose_name='내용')
    uploaded_paths = models.JSONField(
        default=list,
        blank=True,
        help_text="업로드된 파일 경로 목록"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'draft'
        verbose_name = '게시글 작성 버퍼'
        verbose_name_plural = '게시글 작성 버퍼 목록'
        ordering = ['-updated_at']

    def __str__(self):
        board_name = self.board.name if self.board else '게시판 미선택'
        return f'{self.author.email} - {board_name} 버퍼'