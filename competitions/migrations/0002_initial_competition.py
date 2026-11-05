from django.db import migrations


def create_competition(apps, schema_editor):
    apps.get_model('competitions', 'Competition').objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [('competitions', '0001_initial')]
    operations = [migrations.RunPython(create_competition, migrations.RunPython.noop)]
