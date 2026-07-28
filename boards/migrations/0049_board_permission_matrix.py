from django.db import migrations, models


# 게시판 권한을 조회/작성/댓글 3축 매트릭스로 승격하고 관리자 페이지에서 전면 편집하게
# 하는 변경의 데이터 파트.
#
# 1) read_permission에 'author'(작성자 본인+스태프) 선택지를 추가한다.
#    사유서·에러/피드백 제보의 "본인만 조회"가 지금까지 board_type=3에 숨어 있어
#    관리자 화면에 '전체공개'로 표시되던 것을 정식 값으로 드러낸다.
# 2) Board.save()의 board_type 기반 post/comment 권한 자동 파생을 제거했으므로,
#    지금까지 파생되던 값을 명시적 데이터로 한 번 고정한다(백필).
# 3) 사유서형(board_type=3) 게시판의 read_permission을 'author'로 세운다.
#    진입은 로그인 회원(제출·본인 글 확인), 글 조회는 본인+스태프 — 실제 동작 그대로.
#
# ─ 이 변경은 접근을 '조이기만' 하며(all → author) 절대 느슨하게 하지 않는다.
# ─ 배포 이후에는 관리자 페이지(게시판 관리)에서 3축 모두 변경할 수 있다.


def apply_permission_matrix(apps, schema_editor):
    Board = apps.get_model('boards', 'Board')
    # 기존 save() 파생 규칙의 백필: ADMIN(2) → 작성 스태프, GENERAL(1) → 전부 회원,
    # JUSTIFICATION(3) → 작성 회원·댓글 스태프. 사진첩(4)은 파생 대상이 아니었으므로 유지.
    Board.objects.filter(board_type=2).update(post_permission='staff', comment_permission='all')
    Board.objects.filter(board_type=1).update(post_permission='all', comment_permission='all')
    Board.objects.filter(board_type=3).update(
        read_permission='author', post_permission='all', comment_permission='staff',
    )


def noop(apps, schema_editor):
    # 되돌릴 때 접근 범위를 임의로 넓히지 않도록 no-op으로 둔다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0048_set_initial_board_visibility'),
    ]

    operations = [
        migrations.AlterField(
            model_name='board',
            name='read_permission',
            field=models.CharField(
                choices=[
                    ('all', 'All'),
                    ('member', 'Member'),
                    ('author', 'Author'),
                    ('staff', 'Staff'),
                ],
                default='all',
                max_length=10,
            ),
        ),
        migrations.RunPython(apply_permission_matrix, noop),
    ]
