from django.contrib import admin
from .models import Board, Post, Comment, Attachment

admin.site.register(Board)
admin.site.register(Post)
admin.site.register(Comment)
admin.site.register(Attachment)