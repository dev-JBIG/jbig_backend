import random
import uuid
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.files.base import ContentFile
from users.models import User
from boards.models import Category, Board, Post, Comment

class Command(BaseCommand):
    help = 'DB에 초기 데이터를 생성합니다. (Users, Categories, Boards, Posts, Comments)'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('기존 데이터를 삭제합니다...')
        Comment.objects.all().delete()
        Post.objects.all().delete()
        Board.objects.all().delete()
        Category.objects.all().delete()
        User.objects.all().delete()

        self.stdout.write('새로운 데이터를 생성합니다...')

        # 1. 사용자 생성
        users = [
            User.objects.create_user(email='user1@test.com', username='김철수', password='password123', semester=1),
            User.objects.create_user(email='user2@test.com', username='이영희', password='password123', semester=2),
            User.objects.create_superuser(email='admin@test.com', username='관리자', password='password123', semester=3)
        ]
        self.stdout.write(self.style.SUCCESS('-> 사용자 3명 생성 완료'))

        # 2. 카테고리 및 게시판 생성
        board_data = {
            "공지": ["공지사항"],
            "커뮤니티": ["자유게시판", "질문게시판"],
        }
        for cat_name, board_names in board_data.items():
            category = Category.objects.create(name=cat_name)
            for board_name in board_names:
                Board.objects.create(name=board_name, category=category)
        self.stdout.write(self.style.SUCCESS('-> 카테고리 및 게시판 생성 완료'))

        # 3. 게시글 및 댓글 생성
        boards = Board.objects.all()
        for board in boards:
            self.stdout.write(f'-- "{board.name}" 게시판에 데이터 생성 중...')
            for i in range(5):
                author = random.choice(users)
                title = f'{board.name}의 {i+1}번째 테스트 게시글'
                
                # HTML 내용 생성
                html_content_str = f"""
                <h1>{title}</h1>
                <p>이것은 <b>{author.username}</b>님이 작성한 테스트용 HTML 콘텐츠입니다.</p>
                <p>HTML 검색 기능을 테스트하기 위한 특별한 키워드: <b>QuantumLeap</b></p>
                """
                
                # Post 인스턴스 생성 (DB 저장 전)
                post = Post(author=author, board=board, title=title)
                
                # HTML 내용을 ContentFile로 변환하여 저장
                file_name = f"{uuid.uuid4()}.html"
                post.content_html.save(file_name, ContentFile(html_content_str), save=False)
                
                # Post 인스턴스를 DB에 저장
                post.save()

                # 댓글 생성
                for j in range(2):
                    Comment.objects.create(
                        post=post,
                        author=random.choice(users),
                        content=f'{post.title}의 {j+1}번째 댓글입니다.'
                    )
        
        self.stdout.write(self.style.SUCCESS('-> 게시글 및 댓글 생성 완료'))
        self.stdout.write(self.style.SUCCESS('===================================='))
        self.stdout.write(self.style.SUCCESS('모든 데이터 생성이 성공적으로 완료되었습니다.'))
        self.stdout.write(self.style.SUCCESS('===================================='))
