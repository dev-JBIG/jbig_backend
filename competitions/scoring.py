"""Only the grading worker/management commands import this module; never API views."""
import csv
import hashlib
import io
import json
import math
import uuid
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from .csv_validation import rmse, validate_submission
from .files import private_root, read_expected_ids, submission_path
from .models import Submission


def evaluate(submission):
    dataset = submission.dataset
    if dataset.evaluator_version != 'adr-rmse-v1':
        raise ValueError('Evaluator version mismatch')
    expected_ids = read_expected_ids(dataset)
    grading = private_root('ARENA_GRADING_ROOT') / dataset.version
    contents = {name: (grading / filename).read_bytes() for name, filename in (
        ('labels', 'test_labels.csv'), ('split', 'split.json'),
    )}
    for name, content in contents.items():
        if hashlib.sha256(content).hexdigest() != dataset.hashes[name]:
            raise ValueError('Grading version mismatch')
    rows = list(csv.DictReader(io.StringIO(contents['labels'].decode('utf-8-sig'), newline='')))
    labels = {row['reservation_id']: float(row['adr']) for row in rows}
    if len(rows) != dataset.test_rows or set(labels) != set(expected_ids) or not all(math.isfinite(v) and v >= 0 for v in labels.values()):
        raise ValueError('Grading labels mismatch')
    split = json.loads(contents['split'])
    public, private = split['public_ids'], split['private_ids']
    if (
        len(public) != dataset.public_rows or len(private) != dataset.private_rows
        or len(set(public)) != len(public) or len(set(private)) != len(private)
        or set(public) & set(private) or set(public) | set(private) != set(expected_ids)
    ):
        raise ValueError('Grading split mismatch')
    content = submission_path(submission).read_bytes()
    if hashlib.sha256(content).hexdigest() != submission.content_hash:
        raise ValueError('Submission content mismatch')
    predictions = validate_submission(content, set(expected_ids))
    return tuple(rmse([labels[rid] for rid in ids], [predictions[rid] for rid in ids]) for ids in (public, private))


def claim_next():
    now = timezone.now()
    ready = Q(status=Submission.Status.QUEUED) | Q(
        status=Submission.Status.SCORING, lease_until__lt=now,
    )
    with transaction.atomic():
        query = Submission.objects.filter(ready).order_by('accepted_at', 'id')
        if connection.features.has_select_for_update_skip_locked:
            query = query.select_for_update(skip_locked=True)
        else:
            query = query.select_for_update()
        submission = query.first()
        if submission is None:
            return None
        token = uuid.uuid4()
        updated = Submission.objects.filter(pk=submission.pk).filter(ready).update(
            status=Submission.Status.SCORING, worker_token=token,
            lease_until=now + timedelta(minutes=5), attempts=F('attempts') + 1,
        )
        if not updated:
            return None
        submission.refresh_from_db()
        return submission


def score_next():
    submission = claim_next()
    if submission is None:
        return None
    try:
        public, private = evaluate(submission)
    except Exception:
        # No exception strings, paths, source rows or tracebacks in participant-facing logs.
        Submission.objects.filter(pk=submission.pk, worker_token=submission.worker_token).update(
            status=Submission.Status.ERROR, worker_token=None, lease_until=None,
        )
        return False
    updated = Submission.objects.filter(
        pk=submission.pk, status=Submission.Status.SCORING, worker_token=submission.worker_token,
    ).update(
        status=Submission.Status.SCORED, public_rmse=public, private_rmse=private,
        worker_token=None, lease_until=None,
    )
    return bool(updated)
