"""
기존 NCP Object Storage의 uploads/ 파일들을 public-read ACL로 일괄 변경하는 커맨드.

사용법:
    python manage.py set_uploads_public_read          # dry-run (변경 없이 대상 확인)
    python manage.py set_uploads_public_read --apply   # 실제 적용
"""
import boto3
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'NCP uploads/ 경로의 기존 파일들에 public-read ACL 적용'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='실제로 ACL을 변경합니다 (기본은 dry-run)')

    def handle(self, *args, **options):
        apply = options['apply']

        s3_client = boto3.client(
            's3',
            endpoint_url=settings.NCP_ENDPOINT_URL,
            aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
            aws_secret_access_key=settings.NCP_SECRET_KEY,
            region_name=settings.NCP_REGION_NAME,
        )

        bucket = settings.NCP_BUCKET_NAME
        prefix = 'uploads/'

        paginator = s3_client.get_paginator('list_objects_v2')
        total = 0
        updated = 0
        failed = 0

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                total += 1

                if not apply:
                    self.stdout.write(f'[dry-run] {key}')
                    continue

                try:
                    s3_client.put_object_acl(
                        Bucket=bucket,
                        Key=key,
                        ACL='public-read',
                    )
                    updated += 1
                    self.stdout.write(f'[OK] {key}')
                except Exception as e:
                    failed += 1
                    self.stderr.write(f'[FAIL] {key}: {e}')

        if apply:
            self.stdout.write(self.style.SUCCESS(f'\n완료: 전체 {total}개, 성공 {updated}개, 실패 {failed}개'))
        else:
            self.stdout.write(self.style.WARNING(f'\n[dry-run] 대상 파일 {total}개. --apply 옵션으로 실제 적용하세요.'))
