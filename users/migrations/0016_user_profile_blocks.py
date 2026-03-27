import uuid
from django.db import migrations, models


def migrate_resume_to_blocks(apps, schema_editor):
    """기존 resume 텍스트를 profile_blocks의 text 블록으로 변환."""
    User = apps.get_model('users', 'User')
    for user in User.objects.exclude(resume='').exclude(resume__isnull=True):
        user.profile_blocks = [{
            'id': str(uuid.uuid4()),
            'type': 'text',
            'data': {'markdown': user.resume},
            'style': {},
        }]
        user.save(update_fields=['profile_blocks'])


def migrate_blocks_to_resume(apps, schema_editor):
    """롤백: profile_blocks의 첫 번째 text 블록을 resume로 복원."""
    User = apps.get_model('users', 'User')
    for user in User.objects.all():
        if user.profile_blocks:
            text_blocks = [b for b in user.profile_blocks if b.get('type') == 'text']
            if text_blocks:
                user.resume = text_blocks[0].get('data', {}).get('markdown', '')
                user.save(update_fields=['resume'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0015_fix_username_composite_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_blocks',
            field=models.JSONField(blank=True, default=list, verbose_name='프로필 블록'),
        ),
        migrations.RunPython(migrate_resume_to_blocks, migrate_blocks_to_resume),
    ]
