import random
import uuid
import os
from django.core.management.base import BaseCommand
from django.db import transaction, connection
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

        self.stdout.write('Resetting auto-increment sequences for PostgreSQL...')
        with connection.cursor() as cursor:
            cursor.execute("ALTER SEQUENCE user_id_seq RESTART WITH 1;")
            cursor.execute("ALTER SEQUENCE category_id_seq RESTART WITH 1;")
            cursor.execute("ALTER SEQUENCE board_id_seq RESTART WITH 1;")
            cursor.execute("ALTER SEQUENCE post_id_seq RESTART WITH 1;")
            cursor.execute("ALTER SEQUENCE comment_id_seq RESTART WITH 1;")
        self.stdout.write(self.style.SUCCESS('-> ID 시퀀스가 성공적으로 리셋되었습니다.'))

        self.stdout.write('새로운 데이터를 생성합니다...')

        # 1. 사용자 생성
        # 보안: 환경 변수에서 테스트 비밀번호 가져오기
        test_password = os.getenv('SEED_TEST_PASSWORD', '@test1234')
        test_email = os.getenv('SEED_TEST_EMAIL', 'testuser@test.com')
        test_username = os.getenv('SEED_TEST_USERNAME', 'testuser')

        users = [
            User.objects.create_user(email=test_email, username=test_username, password=test_password, semester=99),
        ]
        self.stdout.write(self.style.SUCCESS('-> 테스트 사용자 1명 생성 완료'))

        # 2. 카테고리 및 게시판 생성
        board_data = {
            "공지": ["공지사항", "이벤트 안내"],
            "커뮤니티": ["자유게시판", "질문게시판", "정보공유", "유머게시판"],
            "자료실": ["이미지 자료", "문서 자료", "코드 스니펫"]
        }
        for cat_name, board_names in board_data.items():
            category, created = Category.objects.get_or_create(name=cat_name)
            for board_name in board_names:
                Board.objects.get_or_create(name=board_name, category=category)
        self.stdout.write(self.style.SUCCESS('-> 카테고리 및 게시판 생성 완료'))

        # 3. 게시글, 댓글, 대댓글 생성
        boards = Board.objects.all()
        for board in boards:
            self.stdout.write(f'-- "{board.name}" 게시판에 데이터 생성 중...')
            for i in range(10): # 게시글 10개 생성
                author = random.choice(users)
                title = f'{board.name}의 {i+1}번째 테스트 게시글'
                
                html_content_str = f"""
                <h1>{title}</h1>
                <p>이것은 <b>{author.username}</b>님이 작성한 테스트용 HTML 콘텐츠입니다.</p>
                """
                
                post = Post(author=author, board=board, title=title)
                file_name = f"{uuid.uuid4()}.html"
                post.content_html.save(file_name, ContentFile(html_content_str), save=False)
                post.save()

                # 댓글 5개 생성
                for j in range(5):
                    comment_author = random.choice(users)
                    comment = Comment.objects.create(
                        post=post,
                        author=comment_author,
                        content=f'{post.title}의 {j+1}번째 댓글입니다.'
                    )

                    # 대댓글 1개 생성
                    reply_author = random.choice(users)
                    Comment.objects.create(
                        post=post,
                        author=reply_author,
                        content=f'ㄴ {comment.content}',
                        parent=comment
                    )
        
        self.stdout.write(self.style.SUCCESS('-> 게시글 및 댓글 생성 완료'))
        self.stdout.write(self.style.SUCCESS('===================================='))
        self.stdout.write(self.style.SUCCESS('모든 데이터 생성이 성공적으로 완료되었습니다.'))
        self.stdout.write(self.style.SUCCESS('===================================='))