from django.contrib import admin
from .models import Board, Post, Comment, Attachment

class BoardAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'board_type', 'category')
    list_filter = ('category',)
    search_fields = ('name',)

admin.site.register(Board, BoardAdmin)
admin.site.register(Post)
admin.site.register(Comment)
admin.site.register(Attachment)