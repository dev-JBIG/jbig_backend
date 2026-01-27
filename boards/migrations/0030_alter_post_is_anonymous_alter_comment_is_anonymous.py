# Generated manually on 2026-01-27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0029_set_all_anonymous'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='is_anonymous',
            field=models.BooleanField(default=True, help_text='익명 작성 여부 (True: 회원에게만 실명, False: 비회원에게도 실명 공개)'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='is_anonymous',
            field=models.BooleanField(default=True, help_text='익명 작성 여부 (True: 회원에게만 실명, False: 비회원에게도 실명 공개)'),
        ),
    ]
