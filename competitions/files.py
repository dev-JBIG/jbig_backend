import csv
import hashlib
import os
import io
from pathlib import Path

from django.conf import settings

from .csv_validation import ArenaError


def private_root(setting):
    value = getattr(settings, setting, '')
    if not value:
        raise ArenaError('DATA_UNAVAILABLE', '대회 파일을 준비하고 있습니다. 잠시 후 다시 확인해 주세요.', 503)
    root = Path(value).resolve()
    workspace = settings.BASE_DIR.parent
    forbidden = [settings.BASE_DIR, settings.MEDIA_ROOT, settings.STATIC_ROOT, workspace / 'jbig_frontend', workspace / 'jbig_promopage']
    if any(root == path.resolve() or root.is_relative_to(path.resolve()) for path in forbidden):
        raise ArenaError('STORAGE_CONFIGURATION', '대회 비공개 저장소 설정을 확인해야 합니다.', 503)
    return root


def participant_path(dataset, kind):
    names = {'train': 'train.csv', 'test': 'test.csv', 'sample': 'sample_submission.csv'}
    if kind not in names:
        raise ArenaError('FILE_NOT_FOUND', '다운로드할 파일을 찾을 수 없습니다.', 404)
    return private_root('ARENA_PARTICIPANT_ROOT') / dataset.version / names[kind]


def read_expected_ids(dataset):
    try:
        path = participant_path(dataset, 'test')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != dataset.hashes['test']:
            raise ValueError('Data version mismatch')
        ids = [row['reservation_id'] for row in csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))]
        if len(ids) != dataset.test_rows or len(set(ids)) != len(ids):
            raise ValueError('Data IDs mismatch')
        return ids
    except (OSError, ValueError, KeyError, csv.Error):
        raise ArenaError('DATA_UNAVAILABLE', '대회 데이터를 확인하는 중입니다. 운영진에게 문의해 주세요.', 503) from None


def submission_path(submission):
    return private_root('ARENA_SUBMISSION_ROOT') / str(submission.participant.user_id) / f'{submission.pk}.csv'


def write_private(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
    except OSError:
        path.unlink(missing_ok=True)
        raise
