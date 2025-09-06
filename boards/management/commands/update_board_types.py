from django.core.management.base import BaseCommand
from boards.models import Board, Category

class Command(BaseCommand):
    help = 'Updates existing boards with board_type=1, creates Admin (type 2) and Reason (type 3) boards.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting board type update...'))

        # Get or create a default category if none exists
        default_category, created = Category.objects.get_or_create(name='기타')
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created default category: {default_category.name}'))

        # Create or update Admin board (board_type=2)
        admin_board, created = Board.objects.update_or_create(
            name='어드민',
            defaults={
                'board_type': 2,
                'category': default_category,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Admin board: {admin_board.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated Admin board: {admin_board.name}'))

        # Create or update Reason board (board_type=3)
        reason_board, created = Board.objects.update_or_create(
            name='사유서',
            defaults={
                'board_type': 3,
                'category': default_category,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Reason board: {reason_board.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated Reason board: {reason_board.name}'))

        # Update all other boards to board_type=1
        # Exclude the newly created/updated Admin and Reason boards
        other_boards = Board.objects.exclude(id__in=[admin_board.id, reason_board.id])
        updated_count = other_boards.update(board_type=1)
        self.stdout.write(self.style.SUCCESS(f'Updated {updated_count} existing boards to board_type=1.'))

        self.stdout.write(self.style.SUCCESS('Board type update completed.'))
