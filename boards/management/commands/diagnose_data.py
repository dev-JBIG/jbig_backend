from django.core.management.base import BaseCommand
from boards.models import Board, Post
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Diagnoses board, post, and user data to check for inconsistencies.'

    def handle(self, *args, **options):
        User = get_user_model()

        self.stdout.write(self.style.SUCCESS('--- Diagnosing Boards ---'))
        all_boards = Board.objects.all().order_by('id')
        if not all_boards:
            self.stdout.write('No boards found.')
        else:
            for board in all_boards:
                self.stdout.write(
                    f"Board ID: {board.id}, Name: '{board.name}', "
                    f"Board Type: {board.board_type} ({board.get_board_type_display()})"
                )

        self.stdout.write(self.style.SUCCESS('\n--- Diagnosing Recent 10 Posts ---'))
        recent_posts = Post.objects.all().order_by('-created_at')[:10]
        if not recent_posts:
            self.stdout.write('No posts found.')
        else:
            for post in recent_posts:
                self.stdout.write(
                    f"Post ID: {post.id}, Title: '{post.title[:20]}...', "
                    f"Board: '{post.board.name}', "
                    f"Author Username: '{post.author.username}', Author ID: {post.author.id}, "
                    f"Post Type: {post.post_type} ({post.get_post_type_display()})"
                )
        
        self.stdout.write(self.style.SUCCESS('\n--- Diagnosing Specific Users ---'))
        usernames_to_check = ['임성혁', 'castle_h0326@jbnu.ac.kr']
        for username in usernames_to_check:
            try:
                user = User.objects.get(username=username)
                self.stdout.write(
                    f"Found User -> ID: {user.id}, Username: '{user.username}', Email: '{user.email}'"
                )
            except User.DoesNotExist:
                self.stdout.write(f"User with username '{username}' NOT FOUND.")


        self.stdout.write(self.style.SUCCESS('\n--- Diagnosis Complete ---'))
