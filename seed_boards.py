import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jbig_backend.settings')
django.setup()

from boards.models import Category, Board

def seed_boards():
    print("게시판 및 카테고리 시딩을 시작합니다...")

    # 기존 데이터 삭제 로직 제거

    # 기본 카테고리 가져오기 또는 생성
    general_category, _ = Category.objects.get_or_create(name='General')
    academic_category, _ = Category.objects.get_or_create(name='Academic')
    event_category, _ = Category.objects.get_or_create(name='Event')

    # 기존 게시판들은 그대로 유지하고, 새로운 게시판만 추가
    # 관리자 게시판 추가
    admin_board, created = Board.objects.get_or_create(
        name='관리자 게시판',
        category=general_category,
        defaults={
            'read_permission': 'all',
            'post_permission': 'staff',
            'comment_permission': 'staff'
        }
    )
    if created:
        print(f"'{admin_board.name}' 게시판이 생성되었습니다.")
    else:
        # 이미 존재하는 경우, 권한 업데이트 (선택 사항이지만 일관성을 위해)
        if (admin_board.read_permission != 'all' or
            admin_board.post_permission != 'staff' or
            admin_board.comment_permission != 'staff'):
            admin_board.read_permission = 'all'
            admin_board.post_permission = 'staff'
            admin_board.comment_permission = 'staff'
            admin_board.save()
            print(f"'{admin_board.name}' 게시판의 권한이 업데이트되었습니다.")
        else:
            print(f"'{admin_board.name}' 게시판이 이미 존재하며 권한이 올바르게 설정되어 있습니다.")


    # 사유서 게시판 추가
    reason_board, created = Board.objects.get_or_create(
        name='사유서 게시판',
        category=general_category,
        defaults={
            'read_permission': 'staff', # 작성자 허용은 IsPostAuthorOrStaffForReasonBoard에서 처리
            'post_permission': 'all',
            'comment_permission': 'staff' # 작성자 허용은 별도 권한 클래스에서 처리 필요
        }
    )
    if created:
        print(f"'{reason_board.name}' 게시판이 생성되었습니다.")
    else:
        # 이미 존재하는 경우, 권한 업데이트
        if (reason_board.read_permission != 'staff' or
            reason_board.post_permission != 'all' or
            reason_board.comment_permission != 'staff'):
            reason_board.read_permission = 'staff'
            reason_board.post_permission = 'all'
            reason_board.comment_permission = 'staff'
            reason_board.save()
            print(f"'{reason_board.name}' 게시판의 권한이 업데이트되었습니다.")
        else:
            print(f"'{reason_board.name}' 게시판이 이미 존재하며 권한이 올바르게 설정되어 있습니다.")

    print("게시판 및 카테고리 시딩이 완료되었습니다.")

if __name__ == '__main__':
    seed_boards()