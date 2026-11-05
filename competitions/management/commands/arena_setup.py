import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from competitions.csv_validation import ArenaError
from competitions.data_setup import register_dataset


class Command(BaseCommand):
    help = 'Register the fixed ADR dataset and private grouped split; never opens the competition.'

    def add_arguments(self, parser):
        for name in ('train', 'test', 'labels'):
            parser.add_argument(f'--{name}', required=True, type=Path)
        parser.add_argument('--data-version', default='hotel-adr-v1')
        parser.add_argument('--seed', type=int, default=20261105)

    def handle(self, *args, **options):
        version = options['data_version']
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', version):
            raise CommandError('버전 이름은 영문·숫자·하이픈·밑줄 1~64자여야 합니다.')
        try:
            manifest = register_dataset({name: options[name] for name in ('train', 'test', 'labels')}, version, options['seed'])
        except (OSError, ValueError, KeyError, ArenaError) as exc:
            message = exc.message if isinstance(exc, ArenaError) else '데이터 등록에 실패했습니다. 입력 파일과 비공개 저장소 설정을 확인하세요.'
            raise CommandError(message) from None
        self.stdout.write(json.dumps({
            'version': version, 'test_rows': manifest['test_rows'], 'public_rows': manifest['public_rows'],
            'private_rows': manifest['private_rows'], 'public_ratio': manifest['public_rows'] / manifest['test_rows'],
            'private_ratio': manifest['private_rows'] / manifest['test_rows'],
            'feature_groups': manifest['groups'], 'largest_group': manifest['largest_group'],
            'strata': manifest['strata'], 'state': '일정과 상태는 변경하지 않음',
        }, ensure_ascii=False, indent=2))
