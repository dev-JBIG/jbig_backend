from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from boards.models import Board, Post, Comment, Category
from boards.permissions import IsBoardReadable, IsPostWritable, IsCommentWritable, PostDetailPermission
from rest_framework.test import APIRequestFactory

class Command(BaseCommand):
    help = 'Tests the permission system for boards and posts.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting permission system test...'))
        self.setup_users()
        self.setup_boards()
        self.run_all_tests()
        self.stdout.write(self.style.SUCCESS('Permission system test finished.'))

    def setup_users(self):
        User = get_user_model()
        self.staff_user, _ = User.objects.update_or_create(
            email='test@jbnu.ac.kr',
            defaults={'username': 'test_staff', 'is_staff': True, 'is_superuser': True}
        )
        self.staff_user.set_password('@test1234')
        self.staff_user.save()

        self.normal_user, _ = User.objects.update_or_create(
            email='normal@jbnu.ac.kr',
            defaults={'username': 'normal_user', 'is_staff': False}
        )
        self.normal_user.set_password('@test1234')
        self.normal_user.save()
        self.anonymous_user = AnonymousUser()
        self.stdout.write('Test users are ready.')

    def setup_boards(self):
        self.test_category, _ = Category.objects.get_or_create(name='Permission Test')
        self.public_board, _ = Board.objects.update_or_create(
            name='Public Board',
            defaults={'category': self.test_category, 'read_permission': 'all', 'post_permission': 'all', 'comment_permission': 'all'}
        )
        self.protected_board, _ = Board.objects.update_or_create(
            name='Protected Board',
            defaults={'category': self.test_category, 'read_permission': 'all', 'post_permission': 'staff', 'comment_permission': 'staff'}
        )
        self.private_board, _ = Board.objects.update_or_create(
            name='Private Board',
            defaults={'category': self.test_category, 'read_permission': 'staff', 'post_permission': 'staff', 'comment_permission': 'staff'}
        )
        self.stdout.write('Test boards are ready.')

    def run_all_tests(self):
        users = {
            'Anonymous': self.anonymous_user,
            'Normal User': self.normal_user,
            'Staff User': self.staff_user
        }
        boards = {
            'Public Board': self.public_board,
            'Protected Board': self.protected_board,
            'Private Board': self.private_board
        }

        factory = APIRequestFactory()

        for user_name, user in users.items():
            for board_name, board in boards.items():
                self.stdout.write(f"\n--- Testing as [{user_name}] on [{board_name}] ---")
                request = factory.get('/')
                request.user = user

                # Mock view object
                view = type('MockView', (), {'kwargs': {'board_id': board.id}, 'request': request})()
                view.get_object = lambda: board

                # Test Permissions
                read_result = IsBoardReadable().has_permission(request, view)
                post_result = IsPostWritable().has_permission(request, view)
                comment_result = IsCommentWritable().has_permission(request, view)

                self.stdout.write(f"  Can read list: {read_result}")
                self.stdout.write(f"  Can create post: {post_result}")
                self.stdout.write(f"  Can create comment: {comment_result}")

        self.test_post_level_permissions(factory)

    def test_post_level_permissions(self, factory):
        self.stdout.write("\n--- Testing Post-Level Permissions ---")
        post_default = Post.objects.create(title='Default Post', author=self.normal_user, board=self.public_board, post_type=1)
        post_staff = Post.objects.create(title='Staff Post', author=self.staff_user, board=self.public_board, post_type=2)
        post_justification = Post.objects.create(title='Justification Post', author=self.normal_user, board=self.public_board, post_type=3)

        users = {
            'Anonymous': self.anonymous_user,
            'Normal User': self.normal_user,
            'Author of Justification': self.normal_user,
            'Staff User': self.staff_user
        }

        posts = {
            'Default Post': post_default,
            'Staff-Only Post': post_staff,
            'Justification Post': post_justification
        }

        for user_name, user in users.items():
            self.stdout.write(f"\n--- Checking as [{user_name}] ---")
            for post_name, post in posts.items():
                request = factory.get('/')
                request.user = user
                view = type('MockView', (), {'request': request})()
                
                result = PostDetailPermission().has_object_permission(request, view, post)
                self.stdout.write(f"  Can read {post_name}: {result}")

        post_default.delete()
        post_staff.delete()
        post_justification.delete()
