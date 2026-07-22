from django.db import migrations


# 팀 합의(2026-07): 아래 게시판만 전체공개(비회원 열람/다운로드 가능)로 두고,
# 그 외 '일반(board_type=1)' 게시판은 회원전용(member)으로 초기 설정한다.
# ─ 사진첩(4)/사유서(3)/어드민(2)은 자체 접근 로직이 있어 건드리지 않는다.
#   (특히 사진첩은 회원전용으로 바꾸면 인라인 이미지가 깨진다.)
# ─ 과거 모든 게시판이 read_permission='all'이었으므로 이 변경은 접근을 '조이기만'
#   하며(all → member) 절대 느슨하게 하지 않는다.
# ─ 배포 이후에도 관리자 페이지(게시판 관리)에서 언제든 변경할 수 있다.
PUBLIC_BOARD_NAMES = [
    '자유게시판',
    '스터디/소모임 홍보',
    '자랑게시판',
    '논문리뷰',
]


def set_initial_visibility(apps, schema_editor):
    Board = apps.get_model('boards', 'Board')
    general = Board.objects.filter(board_type=1)
    # 1) 공개 목록에 없는 일반 게시판 → 회원전용
    general.exclude(name__in=PUBLIC_BOARD_NAMES).update(read_permission='member')
    # 2) 합의된 공개 게시판 → 전체공개
    general.filter(name__in=PUBLIC_BOARD_NAMES).update(read_permission='all')


def noop(apps, schema_editor):
    # 되돌릴 때 접근 범위를 임의로 넓히지 않도록 no-op으로 둔다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0047_alter_board_comment_permission_and_more'),
    ]

    operations = [
        migrations.RunPython(set_initial_visibility, noop),
    ]
