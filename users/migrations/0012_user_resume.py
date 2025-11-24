from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0011_remove_user_role_user_groups_user_user_permissions_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='resume',
            field=models.TextField(blank=True, default='', verbose_name='자기소개'),
        ),
    ]
