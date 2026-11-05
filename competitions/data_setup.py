"""Server-only dataset registration. Never imported by the HTTP layer."""
import csv
import hashlib
import io
import json
import math
from collections import defaultdict

from django.db import transaction

from .csv_validation import FEATURES, TEST_COLUMNS, ArenaError
from .files import private_root, write_private
from .models import Competition, DatasetVersion, Submission


CONTRACT_HASHES = {
    'train': '144028da6fee76dbf488ef9314e70bbca69eece297fbdfd5c817e2fb1472b2de',
    'test': 'ecec825a9834d4d9ec43e9e9c77fc353f72495303acaa557b82ebb15cc4f0087',
    'labels': 'a1962640fd2037a0db0e978d3f27b72b89727d4b17ff0810006292c4788b4b00',
}


def build_split(rows, seed):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in FEATURES)].append(row['reservation_id'])
    strata = defaultdict(list)
    for features, ids in groups.items():
        tie = hashlib.sha256((str(seed) + json.dumps(features, ensure_ascii=False)).encode()).hexdigest()
        strata[(features[0], features[3])].append((ids, tie))
    public, private, report = [], [], []
    for stratum, group_list in sorted(strata.items()):
        total = sum(len(ids) for ids, _ in group_list)
        target, taken = round(total * 0.3), 0
        for ids, _ in sorted(group_list, key=lambda item: (-len(item[0]), item[1])):
            if abs(target - taken - len(ids)) < abs(target - taken):
                public.extend(ids)
                taken += len(ids)
            else:
                private.extend(ids)
        report.append({'hotel': stratum[0], 'arrival_month': stratum[1], 'total': total, 'public': taken, 'private': total - taken})
    if not public or not private or set(public) & set(private) or len(public) + len(private) != len(rows):
        raise ValueError('Invalid grouped split')
    return {'public_ids': sorted(public), 'private_ids': sorted(private)}, {
        'groups': len(groups), 'largest_group': max(map(len, groups.values())), 'strata': report,
    }


def register_dataset(paths, version, seed):
    contents = {name: path.read_bytes() for name, path in paths.items()}
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
    if hashes != CONTRACT_HASHES:
        raise ArenaError('DATA_CONTRACT', '지정된 원본 Train/Test/정답 파일의 해시와 일치하지 않습니다.')
    parsed = {}
    for name, content in contents.items():
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
        expected = TEST_COLUMNS + ['adr'] if name == 'train' else TEST_COLUMNS if name == 'test' else ['reservation_id', 'adr']
        if reader.fieldnames != expected:
            raise ValueError('Unexpected dataset columns')
        parsed[name] = list(reader)
        ids = [row['reservation_id'] for row in parsed[name]]
        if len(set(ids)) != len(ids) or any(not rid for rid in ids):
            raise ValueError('Dataset IDs are not unique')
    if len(parsed['train']) != 107964 or len(parsed['test']) != 10213 or len(parsed['labels']) != 10213:
        raise ValueError('Dataset row contract mismatch')
    if {row['reservation_id'] for row in parsed['test']} != {row['reservation_id'] for row in parsed['labels']}:
        raise ValueError('Test/labels IDs differ')
    if not all(math.isfinite(float(row['adr'])) and float(row['adr']) >= 0 for row in parsed['labels']):
        raise ValueError('Labels are not valid ADR values')
    split, report = build_split(parsed['test'], seed)
    split_bytes = json.dumps(split, sort_keys=True, separators=(',', ':')).encode()
    hashes['split'] = hashlib.sha256(split_bytes).hexdigest()
    sample = io.StringIO(newline='')
    writer = csv.writer(sample)
    writer.writerow(['reservation_id', 'adr'])
    writer.writerows((row['reservation_id'], 0) for row in parsed['test'])
    sample_bytes = sample.getvalue().encode('utf-8')
    hashes['sample'] = hashlib.sha256(sample_bytes).hexdigest()
    roots = {name: private_root(setting) for name, setting in (
        ('participant', 'ARENA_PARTICIPANT_ROOT'), ('grading', 'ARENA_GRADING_ROOT'), ('submissions', 'ARENA_SUBMISSION_ROOT'),
    )}
    for a, root_a in roots.items():
        if any(root_a == root_b or root_a.is_relative_to(root_b) or root_b.is_relative_to(root_a) for b, root_b in roots.items() if a != b):
            raise ValueError('Arena storage roots must be separate')
    defaults = dict(train_rows=107964, test_rows=10213, public_rows=len(split['public_ids']), private_rows=len(split['private_ids']), hashes=hashes)
    manifest = {
        'version': version, **defaults, 'evaluator_version': 'adr-rmse-v1',
        'split_algorithm': 'feature-groups-hotel-month-greedy-v1', 'seed': seed, **report,
    }
    with transaction.atomic():
        competition = Competition.objects.select_for_update().get(pk=1)
        previous = DatasetVersion.objects.filter(pk=version).first()
        if previous and previous.hashes != hashes:
            raise ValueError('Existing data version cannot be replaced')
        if competition.dataset_id != version and Submission.objects.exists():
            raise ValueError('Cannot switch datasets after accepting submissions')
        outputs = [
            (roots['participant'] / version / 'train.csv', contents['train']),
            (roots['participant'] / version / 'test.csv', contents['test']),
            (roots['participant'] / version / 'sample_submission.csv', sample_bytes),
            (roots['grading'] / version / 'test_labels.csv', contents['labels']),
            (roots['grading'] / version / 'split.json', split_bytes),
            (roots['grading'] / version / 'manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()),
        ]
        for path, content in outputs:
            if path.exists():
                if path.read_bytes() != content:
                    raise ValueError('Existing data artifact differs')
            else:
                write_private(path, content)
        dataset, _ = DatasetVersion.objects.get_or_create(version=version, defaults=defaults)
        competition.dataset = dataset
        competition.save(update_fields=['dataset'])
    return manifest
