from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0012_user_resume'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='can_use_gpu',
            field=models.BooleanField(default=False, verbose_name='GPU 대여 권한'),
        ),
    ]
