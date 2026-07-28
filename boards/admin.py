from django.contrib import admin
from .models import Board, Post, Comment, Category, CommentLike, Draft

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)

@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    # save()의 board_type 기반 권한 자동 파생이 제거되어 세 권한 필드를 직접 지정한다.
    list_display = ('id', 'name', 'board_type', 'form_type', 'category',
                    'read_permission', 'post_permission', 'comment_permission')
    list_filter = ('board_type', 'form_type', 'category', 'read_permission')
    search_fields = ('name',)
    raw_id_fields = ('category',)

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('id', 'board_post_id', 'title', 'author', 'board', 'created_at', 'views')
    search_fields = ('title', 'author__username')
    list_filter = ('board', 'created_at')
    raw_id_fields = ('author', 'board', 'likes')

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'post', 'created_at', 'is_deleted')
    search_fields = ('post__title', 'author__username')
    list_filter = ('created_at', 'is_deleted')
    raw_id_fields = ('post', 'author', 'parent', 'likes')

@admin.register(CommentLike)
class CommentLikeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'comment', 'created_at')
    search_fields = ('user__username', 'comment__content')
    list_filter = ('created_at',)
    raw_id_fields = ('user', 'comment')

@admin.register(Draft)
class DraftAdmin(admin.ModelAdmin):
    list_display = ('author', 'board', 'title', 'updated_at')
    search_fields = ('author__username', 'author__email', 'title')
    list_filter = ('board', 'updated_at')
    raw_id_fields = ('board',)
    readonly_fields = ('created_at', 'updated_at')
