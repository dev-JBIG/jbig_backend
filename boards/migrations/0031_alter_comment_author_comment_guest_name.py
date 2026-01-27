# Generated manually on 2026-01-27

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('boards', '0030_alter_post_is_anonymous_alter_comment_is_anonymous'),
    ]

    operations = [
        migrations.AlterField(
            model_name='comment',
            name='author',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='comments', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='comment',
            name='guest_id',
            field=models.CharField(blank=True, help_text='비회원 고유 ID (IP 기반)', max_length=100, null=True),
        ),
    ]
