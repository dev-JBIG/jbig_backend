from django.db import migrations


def delete_link_share_board(apps, schema_editor):
    """링크공유 게시판과 해당 게시판의 게시글(cascade)을 제거한다."""
    Board = apps.get_model('boards', 'Board')
    Board.objects.filter(name='링크공유', form_type=3).delete()


def recreate_link_share_board(apps, schema_editor):
    """역방향: 0041과 동일하게 링크공유 게시판을 재생성한다."""
    Category = apps.get_model('boards', 'Category')
    Board = apps.get_model('boards', 'Board')

    category, _ = Category.objects.get_or_create(name='커뮤니티')
    Board.objects.get_or_create(
        name='링크공유',
        defaults={
            'category': category,
            'board_type': 1,
            'form_type': 3,
            'read_permission': 'all',
            'post_permission': 'all',
            'comment_permission': 'all',
            'available_tags': [],
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0042_rename_ncp_key_marker'),
    ]

    operations = [
        migrations.RunPython(delete_link_share_board, recreate_link_share_board),
        migrations.RemoveField(model_name='post', name='link_url'),
        migrations.RemoveField(model_name='post', name='link_title'),
        migrations.RemoveField(model_name='post', name='link_description'),
        migrations.RemoveField(model_name='post', name='link_image_url'),
        migrations.RemoveField(model_name='post', name='link_site_name'),
    ]
