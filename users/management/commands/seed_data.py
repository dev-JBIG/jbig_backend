import random
from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import User, Role
from boards.models import Category, Board, Post, Comment

class Command(BaseCommand):
    help = 'DB에 초기 데이터를 생성합니다. (Roles, Users, Categories, Boards, Posts, Comments)'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('기존 데이터를 삭제합니다...')
        # 순서 중요: 외래 키 제약조건 때문에 참조하는 모델부터 삭제
        Comment.objects.all().delete()
        Post.objects.all().delete()
        Board.objects.all().delete()
        Category.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()

        self.stdout.write('새로운 데이터를 생성합니다...')

        # 1. 역할 생성
        Role.objects.create(name='admin')
        Role.objects.create(name='staff')
        Role.objects.create(name='member')
        self.stdout.write(self.style.SUCCESS('-> 역할 (admin, staff, member) 생성 완료'))

        # 2. 사용자 생성
        admin_user = User.objects.create_superuser(email='admin@test.com', username='admin_user', password='password123', role='admin')
        staff_user = User.objects.create_user(email='staff@test.com', username='staff_user', password='password123', role='staff')
        member_user = User.objects.create_user(email='member@test.com', username='member_user', password='password123', role='member')
        users = [admin_user, staff_user, member_user]
        self.stdout.write(self.style.SUCCESS('-> 사용자 (admin, staff, member) 생성 완료'))

        # 3. 카테고리 및 게시판 생성
        board_data = {
            "공지": ["공지사항", "이벤트 안내"],
            "커뮤니티": ["자유게시판", "질문게시판", "정보공유", "유머게시판"],
            "자료실": ["이미지 자료", "문서 자료", "코드 스니펫"]
        }
        for cat_name, board_names in board_data.items():
            category = Category.objects.create(name=cat_name)
            for board_name in board_names:
                Board.objects.create(name=board_name, category=category)
        self.stdout.write(self.style.SUCCESS('-> 카테고리 및 게시판 생성 완료'))

        # 4. 게시글, 댓글, 대댓글 대량 생성
        boards = Board.objects.all()
        for board in boards:
            self.stdout.write(f'-- "{board.category.name} > {board.name}" 게��판에 데이터 생성 중...')
            for i in range(10): # 게시글 10개
                post = Post.objects.create(
                    author=random.choice(users),
                    board=board,
                    title=f'{board.name}의 {i+1}번째 테스트 게시글',
                    content=f'이것은 {board.name}에 자동으로 생성된 게시글입니다. 내용은 중요하지 않습니다.'
                )
                
                for j in range(2): # 댓글 2개
                    comment = Comment.objects.create(
                        post=post,
                        author=random.choice(users),
                        content=f'{post.title}의 {j+1}번째 댓글입니다.'
                    )

                    for k in range(4): # 대댓글 4개
                        Comment.objects.create(
                            post=post,
                            author=random.choice(users),
                            content=f'{comment.content}에 대한 {k+1}번째 대댓글입니다.',
                            parent=comment
                        )
        
        self.stdout.write(self.style.SUCCESS('-> 게시글, 댓글, 대댓글 대량 생성 완료'))
        self.stdout.write(self.style.SUCCESS('===================================='))
        self.stdout.write(self.style.SUCCESS('모든 데이터 생성이 성공적으로 완료되었습니다.'))
        self.stdout.write(self.style.SUCCESS('===================================='))