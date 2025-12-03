from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GpuInstance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vast_instance_id', models.CharField(max_length=50, unique=True)),
                ('offer_id', models.CharField(max_length=50)),
                ('gpu_name', models.CharField(blank=True, max_length=100)),
                ('hourly_price', models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ('status', models.CharField(choices=[('starting', 'Starting'), ('running', 'Running'), ('stopped', 'Stopped'), ('terminated', 'Terminated')], default='starting', max_length=20)),
                ('jupyter_token', models.CharField(blank=True, max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('terminated_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gpu_instances', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
