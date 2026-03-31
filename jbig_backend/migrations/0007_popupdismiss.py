import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('jbig_backend', '0006_popup_source_post'),
    ]

    operations = [
        migrations.CreateModel(
            name='PopupDismiss',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('popup', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dismissals', to='jbig_backend.popup')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dismissed_popups', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '팝업 확인 기록',
                'verbose_name_plural': '팝업 확인 기록',
                'db_table': 'popup_dismiss',
                'unique_together': {('user', 'popup')},
            },
        ),
    ]
