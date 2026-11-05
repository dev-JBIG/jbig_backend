import csv
import hashlib
import io
import json
import math
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, close_old_connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .csv_validation import FEATURES, MAX_UPLOAD_BYTES, ArenaError, rmse, validate_submission
from .data_setup import build_split
from .files import private_root, submission_path
from .models import Competition, DailyQuota, DatasetVersion, FinalResult, Participant, Submission
from .scoring import claim_next, score_next
from .services import accept_submission, finalize, participant_for, select_final


def csv_bytes(rows, header=('reservation_id', 'adr'), bom=False):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return (('\ufeff' if bom else '') + output.getvalue()).encode()


class FixtureMixin:
    def setUp(self):
        super().setUp()
        cache.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.roots = override_settings(
            ARENA_PARTICIPANT_ROOT=root / 'participant', ARENA_GRADING_ROOT=root / 'grading', ARENA_SUBMISSION_ROOT=root / 'submissions',
        )
        self.roots.enable()
        self.addCleanup(self.roots.disable)
        test = b'reservation_id,hotel\r\n0001,A\r\n"r,2",A\r\nr3,B\r\n'
        self.good = csv_bytes([('0001', 3), ('r,2', 7), ('r3', 9)])
        self.split = json.dumps({'public_ids': ['0001', 'r,2'], 'private_ids': ['r3']}).encode()
        participant = root / 'participant' / 'fixture-v1'
        grading = root / 'grading' / 'fixture-v1'
        participant.mkdir(parents=True)
        grading.mkdir(parents=True)
        (participant / 'test.csv').write_bytes(test)
        (participant / 'train.csv').write_bytes(b'reservation_id,adr\r\na,5\r\n')
        (participant / 'sample_submission.csv').write_bytes(csv_bytes([('0001', 0), ('r,2', 0), ('r3', 0)]))
        self.labels_path = grading / 'test_labels.csv'
        self.labels_path.write_bytes(self.good)
        (grading / 'split.json').write_bytes(self.split)
        self.dataset = DatasetVersion.objects.create(
            version='fixture-v1', train_rows=1, test_rows=3, public_rows=2, private_rows=1,
            hashes={name: hashlib.sha256(data).hexdigest() for name, data in [('test', test), ('labels', self.good), ('split', self.split)]},
        )
        self.competition, _ = Competition.objects.update_or_create(pk=1, defaults={
            'state': Competition.State.OPEN, 'dataset': self.dataset,
            'starts_at': timezone.now() - timedelta(days=1), 'ends_at': timezone.now() + timedelta(days=2),
            'daily_limit': 5, 'finalized_at': None,
        })
        self.user = get_user_model().objects.create_user(
            email='arena-old-member@jbnu.ac.kr', username='예전 기수 회원', semester=1,
            password='ArenaTest!234', is_active=True, is_verified=True,
        )
        self.participant = participant_for(self.user, self.competition)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self, content=None, key=None, filename='submission.csv', client=None):
        return (client or self.client).post('/api/arena/submissions/', {
            'file': SimpleUploadedFile(filename, self.good if content is None else content, content_type='text/csv'),
        }, format='multipart', HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))

    def submit(self, content=None, user=None):
        return accept_submission(user or self.user, self.good if content is None else content, 'submission.csv', uuid.uuid4())[0]


class CSVTests(SimpleTestCase):
    def test_fixed_rmse_zero_and_extreme_finite_values(self):
        self.assertAlmostEqual(rmse([3, 7], [0, 3]), math.sqrt(12.5))
        self.assertEqual(rmse([3, 7], [3, 7]), 0)
        self.assertTrue(math.isfinite(rmse([3, 7], [-1.7976931348623157e308, 1.7976931348623157e308])))

    def test_bom_quotes_crlf_cr_lf_reordered_headers_and_negative(self):
        content = csv_bytes([(-2, 'r,2'), (3, '0001')], header=('adr', 'reservation_id'), bom=True)
        for ending in (b'\r\n', b'\n', b'\r'):
            parsed = validate_submission(content.replace(b'\r\n', ending), {'0001', 'r,2'})
            self.assertEqual(parsed, {'r,2': -2, '0001': 3})

    def test_invalid_values_are_actionable_and_bounded(self):
        for value in ['', 'NaN', 'Infinity', '-inf', 'not-a-number', '1e999']:
            with self.subTest(value=value), self.assertRaises(ArenaError) as caught:
                validate_submission(csv_bytes([('0001', value)]), {'0001'})
            self.assertEqual(caught.exception.errors[0]['record'], 2)
        with self.assertRaises(ArenaError) as caught:
            validate_submission(csv_bytes([(f'unknown-{i}', 'NaN') for i in range(1000)]), {'0001'})
        self.assertLessEqual(len(caught.exception.errors), 30)

    def test_duplicate_missing_unknown_and_string_id(self):
        with self.assertRaises(ArenaError) as caught:
            validate_submission(csv_bytes([('0001', 1), ('0001', 2), ('1', 3)]), {'0001', 'other'})
        codes = {error['code'] for error in caught.exception.errors}
        self.assertTrue({'DUPLICATE_ID', 'MISSING_IDS', 'UNKNOWN_ID'} <= codes)

    def test_headers_encoding_quotes_and_size(self):
        for content in [b'', b'adr,adr\n1,2', b'reservation_id,adr,extra\nx,1,2', b'reservation_id,adr\n"unclosed,1', b'\xff\xfe', b'\x00']:
            with self.subTest(content=content), self.assertRaises(ArenaError):
                validate_submission(content, {'x'})
        with self.assertRaises(ArenaError) as caught:
            validate_submission(b'x' * (MAX_UPLOAD_BYTES + 1), {'x'})
        self.assertEqual(caught.exception.status, 413)

    def test_grouped_split_is_deterministic_and_keeps_identical_inputs_together(self):
        rows = []
        for group, count in enumerate([8, 5, 4, 2, 1, 1, 1]):
            for i in range(count):
                row = {feature: str(group) for feature in FEATURES}
                row.update(hotel='City Hotel', arrival_month='7', reservation_id=f'{group}-{i}')
                rows.append(row)
        split, report = build_split(rows, 42)
        self.assertEqual(split, build_split(list(reversed(rows)), 42)[0])
        for group in range(7):
            sides = {'public' if row['reservation_id'] in split['public_ids'] else 'private' for row in rows if row['lead_time'] == str(group)}
            self.assertEqual(len(sides), 1)
        self.assertEqual(len(split['public_ids']) + len(split['private_ids']), len(rows))
        self.assertEqual(report['groups'], 7)


class ArenaAPITests(FixtureMixin, TestCase):
    def test_old_member_download_submit_score_and_leaderboard(self):
        overview = self.client.get('/api/arena/').data
        self.assertTrue(overview['eligible'])
        self.assertEqual(overview['remaining_today'], 5)
        self.assertNotIn(self.user.username, overview['public_name'])
        for kind in ['train', 'test', 'sample']:
            response = self.client.get(f'/api/arena/downloads/{kind}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            b''.join(response.streaming_content)
        response = self.upload()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['remaining_today'], 4)
        self.assertTrue(score_next())
        board = self.client.get('/api/arena/leaderboard/').data
        self.assertEqual(len(board['results']), 1)
        self.assertEqual(board['results'][0]['score'], 0)
        self.assertTrue(board['results'][0]['is_me'])
        detail = self.client.get(f'/api/arena/submissions/{response.data["submission"]["id"]}/').data
        self.assertEqual(detail['status'], 'scored')
        self.assertIsNone(detail['private_rmse'])

    def test_anonymous_unverified_and_disabled_accounts_are_blocked(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/arena/').status_code, 200)
        for path in ['downloads/test/', 'submissions/', 'leaderboard/']:
            self.assertEqual(self.client.get('/api/arena/' + path).status_code, 401)
        for field in ['is_active', 'is_verified']:
            setattr(self.user, field, False)
            self.client.force_authenticate(self.user)
            self.assertEqual(self.client.get('/api/arena/leaderboard/').status_code, 403)
            setattr(self.user, field, True)

    def test_preparing_and_closed_states_do_not_accept(self):
        for state in ['preparing', 'closed', 'finalized']:
            Competition.objects.filter(pk=1).update(state=state)
            self.assertEqual(self.upload().status_code, 409)
        Competition.objects.filter(pk=1).update(state='preparing')
        self.assertEqual(self.client.get('/api/arena/downloads/test/').status_code, 409)
        self.assertFalse(Submission.objects.exists())

    def test_replay_same_key_counts_once_even_after_closing(self):
        key = uuid.uuid4()
        first = self.upload(key=key)
        Competition.objects.filter(pk=1).update(state='closed')
        replay = self.upload(key=key)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.data['submission']['id'], replay.data['submission']['id'])
        self.assertEqual(DailyQuota.objects.get().used, 1)
        self.assertEqual(Submission.objects.count(), 1)
        mismatch = self.upload(content=csv_bytes([('0001', 1), ('r,2', 2), ('r3', 3)]), key=key)
        self.assertEqual(mismatch.status_code, 409)
        lookup = self.client.get('/api/arena/submissions/', {'request_key': str(key)})
        self.assertEqual(lookup.data['count'], 1)

    def test_invalid_csv_does_not_charge_and_daily_limit_includes_queue(self):
        self.assertEqual(self.upload(content=b'reservation_id,adr\nwrong,NaN').status_code, 400)
        self.assertFalse(DailyQuota.objects.exists())
        for _ in range(5):
            self.assertEqual(self.upload().status_code, 202)
        self.assertEqual(self.upload().status_code, 429)
        self.assertEqual(DailyQuota.objects.get().used, 5)

    def test_oversized_file_and_missing_key(self):
        self.assertEqual(self.upload(content=b'x' * (MAX_UPLOAD_BYTES + 1)).status_code, 413)
        response = self.client.post('/api/arena/submissions/', {'file': SimpleUploadedFile('s.csv', self.good)}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Submission.objects.exists())

    def test_other_users_cannot_list_view_select_or_replay_my_submission(self):
        submission = self.submit()
        other = get_user_model().objects.create_user('other@jbnu.ac.kr', '다른 회원', is_active=True, is_verified=True)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get('/api/arena/submissions/').data['count'], 0)
        self.assertEqual(self.client.get(f'/api/arena/submissions/{submission.pk}/').status_code, 404)
        self.assertEqual(self.client.put('/api/arena/final-selection/', {'submission_id': str(submission.pk)}, format='json').status_code, 404)
        self.assertEqual(self.client.get('/api/arena/submissions/', {'request_key': str(submission.request_key)}).data['count'], 0)

    def test_no_answer_split_raw_file_or_private_scores_in_responses(self):
        submission = self.submit()
        self.assertTrue(score_next())
        for path in ['downloads/labels/', 'downloads/split/', f'submissions/{submission.pk}/file/']:
            self.assertEqual(self.client.get('/api/arena/' + path).status_code, 404)
        for path in ['', 'submissions/', 'leaderboard/']:
            response = self.client.get('/api/arena/' + path)
            body = response.content.decode()
            for secret in ['test_labels.csv', 'public_ids', 'private_ids', self.directory.name, 'content_hash', 'worker_token']:
                self.assertNotIn(secret, body)
        self.assertIsNone(self.client.get(f'/api/arena/submissions/{submission.pk}/').data['private_rmse'])
        with self.assertRaises(ArenaError):
            with override_settings(ARENA_GRADING_ROOT=settings.MEDIA_ROOT / 'grading'):
                private_root('ARENA_GRADING_ROOT')

    def test_shuffled_rows_and_negative_values_score_by_id(self):
        first = self.submit()
        second = self.submit(csv_bytes([('r3', 9), ('0001', 3), ('r,2', 7)], bom=True))
        third = self.submit(csv_bytes([('r3', -9), ('0001', -3), ('r,2', -7)]))
        for _ in range(3):
            self.assertTrue(score_next())
        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual((first.public_rmse, first.private_rmse), (second.public_rmse, second.private_rmse))
        self.assertEqual(third.private_rmse, 18)

    def test_storage_failure_rolls_back_submission_and_quota(self):
        with patch('competitions.services.write_private', side_effect=OSError('private internal detail')):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private internal detail', response.content.decode())
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(DailyQuota.objects.exists())

    def test_worker_error_recovery_does_not_charge_again(self):
        submission = self.submit()
        self.labels_path.write_bytes(b'corrupted server data')
        self.assertFalse(score_next())
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'error')
        self.labels_path.write_bytes(self.good)
        call_command('arena_worker', once=True, retry_errors=True, stdout=io.StringIO())
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'scored')
        self.assertEqual(DailyQuota.objects.get().used, 1)
        self.assertEqual(submission.attempts, 2)

    def test_lost_commit_acknowledgement_keeps_accepted_file_and_replays(self):
        DailyQuota.objects.create(participant=self.participant, day=timezone.now().astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date())
        original_exit = transaction.Atomic.__exit__

        def lost_ack(block, *args):
            original_exit(block, *args)
            raise OperationalError('commit acknowledgement lost')

        key = uuid.uuid4()
        with patch.object(transaction.Atomic, '__exit__', lost_ack), self.assertRaises(ArenaError):
            accept_submission(self.user, self.good, 'submitted.csv', key)
        submission = Submission.objects.get(request_key=key)
        self.assertTrue(submission_path(submission).exists())
        replay, created = accept_submission(self.user, self.good, 'submitted.csv', key)
        self.assertFalse(created)
        self.assertEqual(replay.pk, submission.pk)
        self.assertEqual(DailyQuota.objects.get().used, 1)

    def test_database_failure_before_commit_cleans_file_and_rolls_back_quota(self):
        with patch.object(Submission, 'save', side_effect=ValueError('failed before commit')), self.assertRaises(ValueError):
            self.submit()
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(DailyQuota.objects.exists())
        self.assertEqual(list(Path(self.directory.name).glob('submissions/**/*.csv')), [])

    def test_stale_worker_lease_is_reclaimed_without_new_submission(self):
        submission = self.submit()
        claim = claim_next()
        Submission.objects.filter(pk=submission.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(score_next())
        submission.refresh_from_db()
        self.assertNotEqual(claim.worker_token, submission.worker_token)
        self.assertEqual(submission.status, 'scored')
        self.assertEqual(DailyQuota.objects.get().used, 1)

    def test_kst_midnight_and_exact_deadline(self):
        before = datetime(2026, 11, 5, 14, 59, 59, tzinfo=dt_timezone.utc)
        after = before + timedelta(seconds=1)
        Competition.objects.filter(pk=1).update(starts_at=before - timedelta(days=1), ends_at=after + timedelta(days=1), daily_limit=1)
        with patch('competitions.services.timezone.now', return_value=before):
            self.submit()
        with patch('competitions.services.timezone.now', return_value=after):
            self.submit()
        self.assertEqual(set(DailyQuota.objects.values_list('day', flat=True)), {before.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date(), after.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date()})
        Competition.objects.filter(pk=1).update(ends_at=after)
        with patch('competitions.services.timezone.now', return_value=after), self.assertRaises(ArenaError):
            self.submit()

    def test_pending_submission_can_be_selected_until_deadline(self):
        submission = self.submit()
        response = self.client.put('/api/arena/final-selection/', {'submission_id': str(submission.pk)}, format='json')
        self.assertEqual(response.status_code, 200)
        Competition.objects.filter(pk=1).update(state='closed')
        self.assertEqual(self.client.put('/api/arena/final-selection/', {'submission_id': str(submission.pk)}, format='json').status_code, 409)
        with self.assertRaises(ArenaError):
            finalize()

    def test_public_full_precision_and_final_manual_auto_selection_are_reproducible(self):
        first, second = self.submit(), self.submit()
        other = get_user_model().objects.create_user('old@jbnu.ac.kr', '졸업 회원', semester=1, is_active=True, is_verified=True)
        third = self.submit(user=other)
        for row, public, private in [(first, 1.000049, 8), (second, 2, 2), (third, 1.000041, 2)]:
            Submission.objects.filter(pk=row.pk).update(status='scored', public_rmse=public, private_rmse=private)
        board = self.client.get('/api/arena/leaderboard/').data['results']
        self.assertFalse(board[0]['is_me'])
        self.assertEqual(len(board), 2)
        select_final(self.participant, second.pk)
        Competition.objects.filter(pk=1).update(state='closed')
        self.assertEqual(finalize(), 2)
        snapshot = list(FinalResult.objects.values_list('rank', 'submission_id', 'private_rmse', 'selection_reason'))
        self.assertEqual(snapshot[0][1], second.pk)
        self.assertEqual(snapshot[0][3], 'manual')
        self.assertEqual(snapshot[1][3], 'automatic')
        self.assertEqual(finalize(), 2)
        self.assertEqual(list(FinalResult.objects.values_list('rank', 'submission_id', 'private_rmse', 'selection_reason')), snapshot)
        selected_detail = self.client.get(f'/api/arena/submissions/{second.pk}/').data
        self.assertEqual(selected_detail['private_rmse'], 2)
        self.assertIsNone(self.client.get(f'/api/arena/submissions/{first.pk}/').data['private_rmse'])
        self.assertEqual(self.client.get('/api/arena/leaderboard/').data['metric'], 'private_rmse')

    def test_server_verification_accounts_are_excluded(self):
        Participant.objects.filter(pk=self.participant.pk).update(is_test=True)
        self.submit()
        self.assertTrue(score_next())
        self.assertEqual(self.client.get('/api/arena/leaderboard/').data['results'], [])
        Competition.objects.filter(pk=1).update(state='closed')
        self.assertEqual(finalize(), 0)

    def test_final_result_recomputation_uses_original_files_and_detects_tampering(self):
        self.submit()
        self.assertTrue(score_next())
        Competition.objects.filter(pk=1).update(state='closed')
        finalize()
        output = io.StringIO()
        call_command('arena_check_results', stdout=output)
        self.assertIn('1명 재현 완료', output.getvalue())
        FinalResult.objects.update(private_rmse=123)
        with self.assertRaises(CommandError):
            call_command('arena_check_results', stdout=io.StringIO())


class ConcurrencyTests(FixtureMixin, TransactionTestCase):
    def concurrently(self, keys):
        user_id = self.user.pk

        def submit(key):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                submission, created = accept_submission(user, self.good, 'concurrent.csv', key)
                return str(submission.pk), created
            except ArenaError as exc:
                return exc.code, False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=6) as executor:
            return list(executor.map(submit, keys))

    def test_six_simultaneous_requests_cannot_bypass_five_attempt_limit(self):
        results = self.concurrently([uuid.uuid4() for _ in range(6)])
        self.assertEqual(sum(created for _, created in results), 5, results)
        self.assertEqual(Submission.objects.count(), 5)
        self.assertEqual(DailyQuota.objects.get().used, 5)
        self.assertIn(('DAILY_LIMIT', False), results)

    def test_simultaneous_retries_share_one_submission_and_one_charge(self):
        results = self.concurrently([uuid.uuid4()] * 6)
        self.assertEqual(len({submission_id for submission_id, _ in results}), 1, results)
        self.assertEqual(sum(created for _, created in results), 1, results)
        self.assertEqual(DailyQuota.objects.get().used, 1)
