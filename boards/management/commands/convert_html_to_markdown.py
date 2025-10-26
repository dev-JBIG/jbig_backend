from django.core.management.base import BaseCommand
from bs4 import BeautifulSoup
from boards.models import Post


class Command(BaseCommand):
    help = 'Convert HTML content in post.content_md to clean markdown/text'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without actually changing it',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # HTML 태그가 포함된 게시물 찾기
        posts_with_html = Post.objects.filter(content_md__contains='<')

        if not posts_with_html.exists():
            self.stdout.write(self.style.SUCCESS('No posts with HTML content found.'))
            return

        self.stdout.write(f'Found {posts_with_html.count()} posts with HTML content.')

        for post in posts_with_html:
            old_content = post.content_md

            # BeautifulSoup로 HTML 파싱
            soup = BeautifulSoup(old_content, 'html.parser')

            # 텍스트 추출 (HTML 태그 제거)
            clean_text = soup.get_text()

            # 공백 정리
            clean_text = clean_text.strip()

            self.stdout.write(f'\nPost ID {post.id}: {post.title}')
            self.stdout.write(f'  Before: {old_content[:100]}...')
            self.stdout.write(f'  After:  {clean_text[:100]}...')

            if not dry_run:
                post.content_md = clean_text
                post.save()
                # 검색 벡터도 업데이트
                post.update_search_vector()
                post.save()
                self.stdout.write(self.style.SUCCESS(f'  ✓ Updated'))
            else:
                self.stdout.write(self.style.WARNING(f'  (dry-run, not saved)'))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\nDry-run mode: {posts_with_html.count()} posts would be updated.'
            ))
            self.stdout.write(self.style.WARNING(
                'Run without --dry-run to actually update the database.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nSuccessfully converted {posts_with_html.count()} posts to clean text.'
            ))
