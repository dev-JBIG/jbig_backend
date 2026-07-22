from django.db import migrations


# 팀 합의(2026-07): 아래 성격의 게시판만 전체공개(비회원 열람/다운로드 가능)로 두고,
# 그 외 '일반(board_type=1)' 게시판은 회원전용(member)으로 초기 설정한다.
#
#   공개: 자유게시판 · 스터디/소모임 홍보 · 자랑게시판 · 논문리뷰
#
# 게시판 이름은 프로덕션 DB에만 존재하고 띄어쓰기/슬래시 표기가 다를 수 있어
# (예: '논문 리뷰', '스터디 홍보', '소모임 홍보'), 공백을 제거한 토큰 매칭으로 판별한다.
#
# ─ 사진첩(4)/사유서(3)/어드민(2)은 자체 접근 로직이 있어 건드리지 않는다.
#   (특히 사진첩은 회원전용으로 바꾸면 인라인 이미지가 깨진다.)
# ─ 과거 모든 게시판이 read_permission='all'이었으므로 이 변경은 접근을 '조이기만'
#   하며(all → member) 절대 느슨하게 하지 않는다.
# ─ 배포 이후에도 관리자 페이지(게시판 관리)에서 언제든 변경할 수 있다.


def _is_public(name):
    n = (name or '').replace(' ', '')
    if n in ('자유게시판', '자랑게시판'):
        return True
    if '논문' in n and '리뷰' in n:            # 논문리뷰 / 논문 리뷰
        return True
    if ('스터디' in n or '소모임' in n) and '홍보' in n:  # 스터디/소모임 홍보 및 변형
        return True
    return False


def set_initial_visibility(apps, schema_editor):
    Board = apps.get_model('boards', 'Board')
    general = Board.objects.filter(board_type=1)
    public_ids = [b.id for b in general if _is_public(b.name)]
    # 1) 공개 대상이 아닌 일반 게시판 → 회원전용
    general.exclude(id__in=public_ids).update(read_permission='member')
    # 2) 합의된 공개 게시판 → 전체공개
    Board.objects.filter(id__in=public_ids).update(read_permission='all')


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
