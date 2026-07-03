from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0045_notification_recipient_created_idx'),
    ]

    operations = [
        migrations.AlterField(
            model_name='board',
            name='form_type',
            field=models.IntegerField(
                choices=[(0, 'None'), (1, 'Absence'), (2, 'Feedback')],
                default=0,
                help_text='작성 화면에서 띄울 입력 폼. 권한(board_type)과 별개로 동작한다.',
                verbose_name='작성 폼 종류',
            ),
        ),
    ]
