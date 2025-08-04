
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jbig_backend.settings")
django.setup()

from boards.models import Category, Board

# 기존 데이터 삭제
Category.objects.all().delete()
Board.objects.all().delete()

# 더미 데이터
board_data = [
    { "category": "공지", "boards": ["공지사항", "이벤트 안내"] },
    { "category": "커뮤니티", "boards": ["자유게시판", "질문게시판", "정보공유", "유머게시판"] },
    { "category": "자료실", "boards": ["이미지 자료", "문서 자료", "코드 스니펫"] }
]

# 새 데이터 추가
for item in board_data:
    category_name = item['category']
    category = Category.objects.create(name=category_name)
    for board_name in item['boards']:
        Board.objects.create(name=board_name, category=category)

print("데이터베이스 시딩 완료")
