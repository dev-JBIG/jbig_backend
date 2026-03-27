from django.db import migrations, models


def strip_username_prefix(apps, schema_editor):
    """기존 username에서 '{semester}_' prefix를 제거하여 순수 이름만 남김."""
    User = apps.get_model('users', 'User')
    for user in User.objects.all():
        if '_' in user.username:
            user.username = user.username.split('_', 1)[1]
            user.save(update_fields=['username'])


def restore_username_prefix(apps, schema_editor):
    """롤백: username에 '{semester}_' prefix를 다시 추가."""
    User = apps.get_model('users', 'User')
    for user in User.objects.all():
        if user.semester is not None:
            user.username = f"{user.semester}_{user.username}"
            user.save(update_fields=['username'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0014_remove_user_first_name_remove_user_last_name'),
    ]

    operations = [
        # 1. username의 unique=True 제거 (동명이인 prefix 제거 시 충돌 방지)
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(max_length=150),
        ),
        # 2. 기존 데이터에서 semester_ prefix 제거
        migrations.RunPython(strip_username_prefix, restore_username_prefix),
        # 3. (username, semester) 복합 유니크 제약 추가
        migrations.AlterUniqueTogether(
            name='user',
            unique_together={('username', 'semester')},
        ),
    ]
