from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import User, Role
from boards.models import Category, Board, Post, Comment

class Command(BaseCommand):
    help = 'DB에 초기 데이터를 생성합니다. (Roles, Users, Posts, Comments)'

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
        role_admin = Role.objects.create(name='admin')
        role_staff = Role.objects.create(name='staff')
        role_member = Role.objects.create(name='member')
        self.stdout.write(self.style.SUCCESS('-> 역할 (admin, staff, member) 생성 완료'))

        # 2. 사용자 생성
        admin_user = User.objects.create_superuser(
            email='admin@test.com',
            username='admin_user',
            password='password123',
            role='admin' # UserManager에서 role 이름으로 처리
        )
        staff_user = User.objects.create_user(
            email='staff@test.com',
            username='staff_user',
            password='password123',
            role='staff'
        )
        member_user = User.objects.create_user(
            email='member@test.com',
            username='member_user',
            password='password123',
            role='member'
        )
        self.stdout.write(self.style.SUCCESS('-> 사용자 (admin, staff, member) 생성 완료'))

        # 3. 게시판 생성
        category = Category.objects.create(name='자유게시판')
        board = Board.objects.create(name='일상', category=category)
        self.stdout.write(self.style.SUCCESS('-> 게시판 (자유게시판 > 일상) 생성 완료'))

        # 4. 게시글 생성
        post1 = Post.objects.create(
            author=member_user,
            board=board,
            title='첫 번째 테스트 게시글입니다.',
            content='안녕하세요! 멤버 유저가 작성한 첫 글입니다.'
        )
        Post.objects.create(
            author=member_user,
            board=board,
            title='오늘 날씨가 좋네요',
            content='산책하기 좋은 날씨입니다.'
        )
        Post.objects.create(
            author=member_user,
            board=board,
            title='Django 모델링 재밌네요',
            content='DB 구조를 단순화하니 훨씬 보기 좋습니다.'
        )
        self.stdout.write(self.style.SUCCESS('-> 게시글 3개 생성 완료'))

        # 5. 댓글 및 답글 생성
        comment1 = Comment.objects.create(
            post=post1,
            author=staff_user,
            content='스태프입니다. 글 잘 봤습니다!'
        )
        Comment.objects.create(
            post=post1,
            author=member_user,
            content='댓글 감사합니다!',
            parent=comment1 # comment1에 대한 답글
        )
        self.stdout.write(self.style.SUCCESS('-> 댓글 및 답글 생성 완료'))

        self.stdout.write(self.style.SUCCESS('===================================='))
        self.stdout.write(self.style.SUCCESS('모든 데이터 생성이 성공적으로 완료되었습니다.'))
        self.stdout.write(self.style.SUCCESS('===================================='))
