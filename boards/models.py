import uuid
import os
from django.db import models
from django.conf import settings

def post_upload_path(instance, filename):
    # e.g. media/boards/1/a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6.html
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
    name = models.CharField(max_length=50)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='boards')

    BOARD_TYPE_CHOICES = (
        (1, 'General'),
        (2, 'Admin'),
        (3, 'Reason'),
    )
    board_type = models.IntegerField(choices=BOARD_TYPE_CHOICES, default=1)

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
        permissions = [
            ("can_read_board", "Can read posts on this board"),
            ("can_write_post", "Can write posts on this board"),
            ("can_comment_post", "Can comment on posts on this board"),
        ]

    def __str__(self):
        return self.name

class Post(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='posts')
    title = models.CharField(max_length=200)
    content_html = models.FileField(upload_to=post_upload_path, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    views = models.PositiveIntegerField(default=0)
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        related_name='liked_posts', 
        blank=True,
        through='PostLike'
    )

    POST_TYPE_CHOICES = (
        (1, 'Default'),
        (2, 'Staff Only'),
        (3, 'Justification Letter'),
    )
    post_type = models.IntegerField(choices=POST_TYPE_CHOICES, default=1)

    class Meta:
        db_table = 'post'
        verbose_name = '게시글'
        verbose_name_plural = '게시글 목록'

    def __str__(self):
        return self.title

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

class Attachment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='attachments', null=True, blank=True)
    file = models.FileField(upload_to='attachments/')
    filename = models.CharField(max_length=255)

    class Meta:
        db_table = 'attachment'
        verbose_name = '첨부파일'
        verbose_name_plural = '첨부파일 목록'
    
    def __str__(self):
        return self.filename

    def delete(self, *args, **kwargs):
        # Delete the file from the filesystem
        if self.file and os.path.exists(self.file.path):
            os.remove(self.file.path) # Use os.remove directly
        super().delete(*args, **kwargs)
