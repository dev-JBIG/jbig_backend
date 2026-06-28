from django.db import migrations


OLD_MARKER = 'ncp-key://'
NEW_MARKER = 'media-key://'


def _replace_marker(apps, old, new):
    """Post/Draft 본문에 저장된 내부 키 마커를 일괄 치환한다."""
    for model_name in ('Post', 'Draft'):
        Model = apps.get_model('boards', model_name)
        for obj in Model.objects.filter(content_md__contains=old).iterator():
            obj.content_md = obj.content_md.replace(old, new)
            obj.save(update_fields=['content_md'])


def forwards(apps, schema_editor):
    _replace_marker(apps, OLD_MARKER, NEW_MARKER)


def backwards(apps, schema_editor):
    _replace_marker(apps, NEW_MARKER, OLD_MARKER)


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0041_create_link_share_board'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
