from django.db import migrations


def create_link_share_board(apps, schema_editor):
    Category = apps.get_model('boards', 'Category')
    Board = apps.get_model('boards', 'Board')

    category, _ = Category.objects.get_or_create(name='커뮤니티')
    board, created = Board.objects.get_or_create(
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

    if created:
        return

    update_fields = []
    desired = {
        'category_id': category.id,
        'board_type': 1,
        'form_type': 3,
        'read_permission': 'all',
        'post_permission': 'all',
        'comment_permission': 'all',
        'available_tags': [],
    }
    for field, value in desired.items():
        if getattr(board, field) != value:
            setattr(board, field, value)
            update_fields.append('category' if field == 'category_id' else field)

    if update_fields:
        board.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0040_post_link_description_post_link_image_url_and_more'),
    ]

    operations = [
        migrations.RunPython(create_link_share_board, migrations.RunPython.noop),
    ]
