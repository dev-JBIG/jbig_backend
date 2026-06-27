from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jbig_backend', '0007_popupdismiss'),
    ]

    operations = [
        migrations.AlterField(
            model_name='popup',
            name='image_url',
            field=models.CharField(blank=True, max_length=500, null=True, verbose_name='이미지 경로 (스토리지 key)'),
        ),
    ]
