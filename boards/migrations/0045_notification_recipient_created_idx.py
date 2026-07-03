from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0044_post_board_created_at_idx'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', '-created_at'], name='noti_recipient_created_idx'),
        ),
    ]
