# 기존 게시판에 form_type 초기값을 채운다.
# board_type/이름 기반 휴리스틱은 이 1회성 백필에만 사용하고,
# 이후로는 admin에서 명시적으로 지정한 form_type 값을 신뢰한다.
from django.db import migrations

FEEDBACK_KEYWORDS = ("에러", "피드백", "제보")
JUSTIFICATION_LETTER = 3  # Board.BoardType.JUSTIFICATION_LETTER


def set_form_types(apps, schema_editor):
    Board = apps.get_model('boards', 'Board')
    for board in Board.objects.all():
        name = board.name or ""
        if any(keyword in name for keyword in FEEDBACK_KEYWORDS):
            form_type = 2  # FormType.FEEDBACK
        elif board.board_type == JUSTIFICATION_LETTER or "사유서" in name:
            form_type = 1  # FormType.ABSENCE
        else:
            form_type = 0  # FormType.NONE
        if board.form_type != form_type:
            board.form_type = form_type
            board.save(update_fields=['form_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0038_board_form_type'),
    ]

    operations = [
        migrations.RunPython(set_form_types, migrations.RunPython.noop),
    ]
