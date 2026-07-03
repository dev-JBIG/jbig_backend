from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0043_remove_link_share_board'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='post',
            index=models.Index(fields=['board', '-created_at'], name='post_board_created_at_idx'),
        ),
    ]
