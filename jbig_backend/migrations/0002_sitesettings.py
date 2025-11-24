from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jbig_backend', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteSettings',
            fields=[
                ('key', models.CharField(max_length=100, primary_key=True, serialize=False, unique=True)),
                ('value', models.TextField(blank=True, default='')),
            ],
            options={
                'verbose_name': '사이트 설정',
                'verbose_name_plural': '사이트 설정',
                'db_table': 'site_settings',
            },
        ),
    ]
