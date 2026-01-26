# Generated manually on 2026-01-26

from django.db import migrations


def set_all_anonymous(apps, schema_editor):
    """모든 게시글과 댓글을 익명으로 설정"""
    Post = apps.get_model('boards', 'Post')
    Comment = apps.get_model('boards', 'Comment')
    
    # 모든 게시글을 익명으로 설정
    Post.objects.all().update(is_anonymous=True)
    
    # 모든 댓글을 익명으로 설정
    Comment.objects.all().update(is_anonymous=True)


def reverse_set_all_anonymous(apps, schema_editor):
    """롤백: 모든 게시글과 댓글을 비익명으로 되돌림"""
    Post = apps.get_model('boards', 'Post')
    Comment = apps.get_model('boards', 'Comment')
    
    # 모든 게시글을 비익명으로 설정
    Post.objects.all().update(is_anonymous=False)
    
    # 모든 댓글을 비익명으로 설정
    Comment.objects.all().update(is_anonymous=False)


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0028_comment_is_anonymous_post_is_anonymous'),
    ]

    operations = [
        migrations.RunPython(set_all_anonymous, reverse_set_all_anonymous),
    ]
