from django.db import migrations


def drop_attachment_if_exists(apps, schema_editor):
    connection = schema_editor.connection
    table_names = connection.introspection.table_names()
    if 'attachment' in table_names:
        if connection.vendor == 'postgresql':
            schema_editor.execute("DROP TABLE attachment CASCADE;")
        else:
            schema_editor.execute("DROP TABLE attachment;")


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0036_clear_brag_board_tags'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(drop_attachment_if_exists, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.DeleteModel(
                    name='Attachment',
                ),
            ],
        ),
    ]
