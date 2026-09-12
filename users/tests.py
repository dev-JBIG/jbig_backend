from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch
from smtplib import SMTPException

from boards.models import Board, Category, Comment, Post
from users.models import EmailVerificationCode, PasswordResetToken, User
from users.password_reset_token import (
    RESET_TOKEN_TTL_SECONDS,
    _hash,
    issue_reset_token,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailRecoveryTest(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = APIClient()
        self.data = dict(email='recovery@jbnu.ac.kr', username='recovery',
                         password='Password!1x', semester=1)

    def post(self, name, data):
        return self.client.post(reverse(name), data, format='json')

    def pending_user(self):
        return User.objects.create_user(**self.data)

    def verify(self, code):
        return self.post('email-verify', dict(email=self.data['email'], verifyCode=code))

    def resend(self):
        return self.post('resend-verify-email', dict(email=self.data['email']))

    def assert_no_tokens(self, response):
        self.assertNotIn('access', response.data)
        self.assertNotIn('refresh', response.data)

    def test_signup_mail_failures_rollback_and_allow_retry(self):
        for failure in (SMTPException('unavailable'), ConnectionError('offline'),
                        TimeoutError('timeout'), OSError('network unreachable'), 0):
            with self.subTest(failure=failure):
                with patch('users.serializers.send_mail') as send:
                    if isinstance(failure, Exception):
                        send.side_effect = failure
                    else:
                        send.return_value = failure
                    response = self.post('signup', self.data)
                self.assertEqual(response.status_code, 503)
                self.assertIn('다시', response.data['message'])
                self.assertFalse(User.objects.exists())
                self.assertFalse(EmailVerificationCode.objects.exists())
                with patch('users.serializers.send_mail', return_value=1):
                    self.assertEqual(self.post('signup', self.data).status_code, 201)
                User.objects.all().delete()

    def test_resend_failures_preserve_code_timestamp_and_attempts(self):
        user = self.pending_user()
        original = EmailVerificationCode.objects.create(
            user=user, code=make_password('123456'), attempt_count=3)
        EmailVerificationCode.objects.filter(pk=original.pk).update(
            created_at=timezone.now() - timedelta(minutes=2))
        original.refresh_from_db()
        for failure in (SMTPException('unavailable'), ConnectionError('offline'),
                        OSError('network unreachable'), 0):
            with self.subTest(failure=failure):
                with patch('users.views.send_mail') as send:
                    if isinstance(failure, Exception):
                        send.side_effect = failure
                    else:
                        send.return_value = failure
                    response = self.resend()
                self.assertEqual(response.status_code, 503)
                current = EmailVerificationCode.objects.get(user=user)
                self.assertEqual((current.code, current.created_at, current.attempt_count),
                                 (original.code, original.created_at, original.attempt_count))

    def test_resend_failure_without_code_leaves_no_code(self):
        self.pending_user()
        with patch('users.views.send_mail', return_value=0):
            self.assertEqual(self.resend().status_code, 503)
        self.assertFalse(EmailVerificationCode.objects.exists())

    def test_programming_errors_are_not_hidden(self):
        with patch('users.serializers.send_mail', side_effect=TypeError('bug')):
            with self.assertRaises(TypeError):
                self.post('signup', self.data)
        self.assertFalse(User.objects.exists())

    def test_signup_wrong_code_then_correct_and_login(self):
        with patch('users.serializers.send_mail', return_value=1) as send:
            response = self.post('signup', self.data)
        self.assertEqual(response.status_code, 201)
        self.assert_no_tokens(response)
        code = send.call_args.args[1].split()[-1]
        user = User.objects.get(email=self.data['email'])
        self.assertNotEqual(user.verification_code.code, code)
        self.assertEqual(self.verify('wrong').status_code, 400)
        user.verification_code.refresh_from_db()
        self.assertEqual(user.verification_code.attempt_count, 1)
        response = self.verify(code)
        self.assertEqual(response.status_code, 200)
        self.assert_no_tokens(response)
        self.assertFalse(EmailVerificationCode.objects.exists())
        response = self.post('signin', self.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    def test_expired_missing_and_locked_codes_recover(self):
        for state in ('expired', 'missing', 'locked'):
            with self.subTest(state=state):
                user = self.pending_user()
                if state != 'missing':
                    obj = EmailVerificationCode.objects.create(user=user, code=make_password('123456'))
                    if state == 'expired':
                        EmailVerificationCode.objects.filter(pk=obj.pk).update(
                            created_at=timezone.now() - timedelta(minutes=6))
                        self.assertEqual(self.verify('123456').status_code, 400)
                    else:
                        for _ in range(5):
                            self.assertEqual(self.verify('wrong').status_code, 400)
                    self.assertFalse(EmailVerificationCode.objects.exists())
                response = self.post('signin', self.data)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.data['errorCode'], 'ACCOUNT_NOT_VERIFIED')
                self.assert_no_tokens(response)
                with patch('users.views.send_mail', return_value=1) as send:
                    self.assertEqual(self.resend().status_code, 200)
                new_code = send.call_args.args[1].split()[-1]
                self.assertEqual(EmailVerificationCode.objects.get(user=user).attempt_count, 0)
                self.assertEqual(self.verify(new_code).status_code, 200)
                User.objects.all().delete()

    def test_wrong_credentials_and_verified_inactive_remain_blocked(self):
        user = self.pending_user()
        wrong = self.post('signin', {**self.data, 'password': 'Wrong!123'})
        unknown = self.post('signin', {**self.data, 'email': 'unknown@jbnu.ac.kr'})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.data, unknown.data)
        self.assertEqual(wrong.data['errorCode'], 'INVALID_CREDENTIALS')
        self.assert_no_tokens(wrong)
        user.is_verified = True
        user.save()
        self.assertEqual(self.verify('123456').status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        response = self.post('signin', self.data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['errorCode'], 'ACCOUNT_INACTIVE')
        self.assert_no_tokens(response)

    def test_pending_login_keeps_expired_code_until_explicit_resend(self):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
        user = self.pending_user()
        obj = EmailVerificationCode.objects.create(user=user, code=make_password('123456'))
        EmailVerificationCode.objects.filter(pk=obj.pk).update(
            created_at=timezone.now() - timedelta(minutes=6))
        with patch('users.views.send_mail', return_value=1) as send:
            response = self.post('signin', self.data)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data['errorCode'], 'ACCOUNT_NOT_VERIFIED')
            send.assert_not_called()
            self.assertTrue(EmailVerificationCode.objects.filter(pk=obj.pk).exists())
            self.assertFalse(OutstandingToken.objects.exists())
            with patch('users.views.random.choices', return_value=list('654321')):
                self.assertEqual(self.resend().status_code, 200)
        self.assertEqual(self.verify('123456').status_code, 400)
        self.assertEqual(self.verify('654321').status_code, 200)

    def test_duplicate_signup_preserves_existing_identity(self):
        user = self.pending_user()
        old_password = user.password
        response = self.post('signup', {**self.data, 'username': 'changed',
                                       'semester': 2, 'password': 'Other!123'})
        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertEqual((user.username, user.semester, user.password),
                         (self.data['username'], 1, old_password))

    def test_resend_public_response_does_not_distinguish_accounts(self):
        unknown = self.resend()
        user = self.pending_user()
        with patch('users.views.send_mail', return_value=1):
            pending = self.resend()
        user.is_verified = True
        user.save()
        with patch('users.views.send_mail') as send:
            verified = self.resend()
        send.assert_not_called()
        self.assertEqual((unknown.status_code, unknown.data), (pending.status_code, pending.data))
        self.assertEqual((verified.status_code, verified.data), (pending.status_code, pending.data))


# 테스트 동안 DRF throttle로 인한 429 응답을 막기 위해 매우 넉넉한 rate 를 주입한다.
NO_THROTTLE_REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'jbig_backend.pagination.CustomPagination',
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {},
}


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class UserEmailVerificationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup_url = reverse('signup')
        self.email_verify_url = reverse('email-verify')
        self.user_data = {
            'email': 'testuser@jbnu.ac.kr',
            'username': 'testuser',
            'password': 'testpassword123',
            'semester': 1,
        }

    @patch('users.serializers.send_mail')
    def test_email_verification_flow(self, mock_send_mail):
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)

        mock_send_mail.assert_called_once()
        message = mock_send_mail.call_args[0][1]
        sent_code = message.split(" ")[-1]

        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(user.is_verified)

        verify_data = {
            'email': self.user_data['email'],
            'verifyCode': sent_code,
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertEqual(verify_response.data['message'], 'Email verified successfully.')

        user.refresh_from_db()
        self.assertTrue(user.is_verified)
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())

    @patch('users.serializers.send_mail')
    def test_email_verification_with_invalid_code(self, mock_send_mail):
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)

        verify_data = {
            'email': self.user_data['email'],
            'verifyCode': '123456',
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_400_BAD_REQUEST)

        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(user.is_verified)

    def test_email_verification_generic_error_for_unknown_user(self):
        """존재하지 않는 사용자에게도 인증 실패(400)와 동일한 응답을 준다 (enumeration 차단)."""
        verify_data = {
            'email': 'nonexistent@jbnu.ac.kr',
            'verifyCode': '123456',
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('users.serializers.send_mail')
    def test_email_verification_attempt_count_locks_code(self, mock_send_mail):
        """5회 실패 시 인증 코드가 무효화되어야 한다 (brute-force 방어)."""
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)

        bad = {'email': self.user_data['email'], 'verifyCode': '000000'}
        for _ in range(4):
            res = self.client.post(self.email_verify_url, bad, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        # 5번째 실패에 코드가 삭제된다.
        res = self.client.post(self.email_verify_url, bad, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class SignUpDomainEnforcementTest(TestCase):
    """회원가입은 반드시 @jbnu.ac.kr 이메일만 허용되어야 한다."""

    def setUp(self):
        self.client = APIClient()
        self.signup_url = reverse('signup')

    @patch('users.serializers.send_mail')
    def test_non_jbnu_email_rejected(self, mock_send_mail):
        response = self.client.post(
            self.signup_url,
            {
                'email': 'attacker@gmail.com',
                'username': 'x',
                'password': 'Password!1x',
                'semester': 1,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_send_mail.assert_not_called()
        self.assertFalse(User.objects.filter(email__iexact='attacker@gmail.com').exists())

    @patch('users.serializers.send_mail')
    def test_jbnu_email_accepted_and_normalized(self, mock_send_mail):
        response = self.client.post(
            self.signup_url,
            {
                'email': 'Student@JBNU.AC.KR',
                'username': 'stu',
                'password': 'Password!1x',
                'semester': 1,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # 이메일은 소문자로 정규화되어 저장되어야 한다.
        self.assertTrue(User.objects.filter(email='student@jbnu.ac.kr').exists())


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class PasswordResetFlowTest(TestCase):
    """비밀번호 재설정 플로우: DB에 저장된 opaque 토큰을 통해 인증을 강제한다."""

    def setUp(self):
        self.client = APIClient()
        self.request_url = reverse('password-reset-request')
        self.verify_url = reverse('password-reset-verify')
        self.reset_url = reverse('password-reset')
        self.email = 'resetme@jbnu.ac.kr'
        self.old_password = 'OldPassword!1'
        self.new_password = 'NewPassword!2'
        self.user = User.objects.create_user(
            email=self.email,
            username='resetme',
            password=self.old_password,
            semester=1,
        )
        self.user.is_active = True
        self.user.is_verified = True
        self.user.save()
        self.raw_code = '123456'
        EmailVerificationCode.objects.create(
            user=self.user,
            code=make_password(self.raw_code),
        )

    def _reset_payload(self, token, email=None, new_password=None):
        pw = new_password or self.new_password
        return {
            'email': email or self.email,
            'reset_token': token,
            'new_password1': pw,
            'new_password2': pw,
        }

    def _verify(self, email=None):
        return self.client.post(
            self.verify_url,
            {'email': email or self.email, 'verification_code': self.raw_code},
            format='json',
        )

    def test_verify_creates_db_token_and_removes_code(self):
        response = self._verify()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        raw = response.data['reset_token']
        self.assertTrue(raw)
        self.assertEqual(response.data['expires_in'], RESET_TOKEN_TTL_SECONDS)

        self.assertFalse(EmailVerificationCode.objects.filter(user=self.user).exists())

        record = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(record.token_hash, _hash(raw))
        self.assertNotIn(raw, record.token_hash)
        self.assertIsNone(record.used_at)
        self.assertGreater(record.expires_at, timezone.now())

    def test_verify_with_mixed_case_email_works(self):
        response = self._verify(email=self.email.upper())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('reset_token', response.data)

    def test_verify_invalidates_previous_active_tokens(self):
        first = self._verify()
        EmailVerificationCode.objects.create(
            user=self.user,
            code=make_password(self.raw_code),
        )
        second = self._verify()
        self.assertEqual(second.status_code, status.HTTP_200_OK)

        first_record = PasswordResetToken.objects.get(token_hash=_hash(first.data['reset_token']))
        self.assertIsNotNone(first_record.used_at)

        response = self.client.post(
            self.reset_url,
            self._reset_payload(first.data['reset_token']),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_succeeds_with_valid_token(self):
        verify_response = self._verify()
        token = verify_response.data['reset_token']

        response = self.client.post(self.reset_url, self._reset_payload(token), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))

        record = PasswordResetToken.objects.get(token_hash=_hash(token))
        self.assertIsNotNone(record.used_at)

    def test_reset_without_token_rejected(self):
        """핵심 취약점 방지: 이전 단계 토큰 없이는 재설정 불가."""
        response = self.client.post(
            self.reset_url,
            {
                'email': self.email,
                'new_password1': self.new_password,
                'new_password2': self.new_password,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_with_garbage_token_rejected(self):
        response = self.client.post(
            self.reset_url,
            self._reset_payload('not-a-real-token'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_with_token_for_different_email_rejected(self):
        other = User.objects.create_user(
            email='other@jbnu.ac.kr',
            username='other',
            password='SomePassword!9',
            semester=1,
        )
        other.is_active = True
        other.save()
        raw_other, _ = issue_reset_token(other)

        response = self.client.post(
            self.reset_url,
            self._reset_payload(raw_other),  # email=self.email
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_with_expired_token_rejected(self):
        raw, _ = issue_reset_token(self.user)
        PasswordResetToken.objects.filter(token_hash=_hash(raw)).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        response = self.client.post(self.reset_url, self._reset_payload(raw), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_token_is_single_use(self):
        verify_response = self._verify()
        token = verify_response.data['reset_token']

        first = self.client.post(self.reset_url, self._reset_payload(token), format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.post(
            self.reset_url,
            self._reset_payload(token, new_password='ThirdPassword!3'),
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password('ThirdPassword!3'))

    def test_plaintext_token_not_stored(self):
        raw, _ = issue_reset_token(self.user)
        self.assertFalse(PasswordResetToken.objects.filter(token_hash=raw).exists())
        self.assertTrue(PasswordResetToken.objects.filter(token_hash=_hash(raw)).exists())

    # ─── 사용자 열거 & 에러 메시지 통일 ───

    @patch('users.views.send_mail')
    def test_request_response_identical_for_unknown_email(self, mock_send_mail):
        """미가입 이메일로 요청해도 동일한 200 응답을 받아야 한다 (enumeration 방지)."""
        real = self.client.post(self.request_url, {'email': self.email}, format='json')
        fake = self.client.post(self.request_url, {'email': 'nobody@jbnu.ac.kr'}, format='json')
        self.assertEqual(real.status_code, status.HTTP_200_OK)
        self.assertEqual(fake.status_code, status.HTTP_200_OK)
        self.assertEqual(real.data, fake.data)
        # 실제 메일은 가입된 이메일에 대해서만 발송된다.
        self.assertEqual(mock_send_mail.call_count, 1)

    def test_verify_generic_error_for_unknown_email(self):
        """verify 실패 경로는 사용자 존재 여부를 구분할 수 없어야 한다."""
        res_known_bad = self.client.post(
            self.verify_url,
            {'email': self.email, 'verification_code': '000000'},
            format='json',
        )
        res_unknown = self.client.post(
            self.verify_url,
            {'email': 'nobody@jbnu.ac.kr', 'verification_code': '000000'},
            format='json',
        )
        self.assertEqual(res_known_bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_unknown.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_known_bad.data, res_unknown.data)

    def test_verify_attempt_lock(self):
        """5회 실패 시 인증 코드가 무효화되어야 한다."""
        for _ in range(5):
            self.client.post(
                self.verify_url,
                {'email': self.email, 'verification_code': '000000'},
                format='json',
            )
        self.assertFalse(EmailVerificationCode.objects.filter(user=self.user).exists())
        # 이후 정상 코드로도 시도가 실패한다.
        res = self._verify()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class SignInEnumerationTest(TestCase):
    """로그인 실패 경로는 존재하지 않는 이메일과 비밀번호 불일치를 구분할 수 없어야 한다."""

    def setUp(self):
        self.client = APIClient()
        self.signin_url = reverse('signin')
        self.email = 'signin@jbnu.ac.kr'
        self.password = 'Password!1x'
        user = User.objects.create_user(
            email=self.email,
            username='signinuser',
            password=self.password,
            semester=1,
        )
        user.is_active = True
        user.is_verified = True
        user.save()

    def _post(self, payload):
        return self.client.post(self.signin_url, payload, format='json')

    def test_unknown_email_and_wrong_password_return_identical_error(self):
        unknown = self._post({'email': 'ghost@jbnu.ac.kr', 'password': 'anything'})
        wrong = self._post({'email': self.email, 'password': 'wrongpass'})
        self.assertEqual(unknown.status_code, wrong.status_code)
        # 두 응답이 완전히 동일해야 enumeration이 불가능하다.
        self.assertEqual(unknown.data, wrong.data)
        # 응답 본문에 'INVALID_CREDENTIALS' 문자열이 어디든 포함되어 있어야 한다.
        self.assertIn('INVALID_CREDENTIALS', unknown.content.decode())

    def test_correct_login_succeeds(self):
        response = self._post({'email': self.email, 'password': self.password})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class LogoutOwnershipTest(TestCase):
    """LogoutView는 현재 인증된 사용자의 refresh 토큰만 blacklist할 수 있어야 한다."""

    def setUp(self):
        self.client = APIClient()
        self.logout_url = reverse('logout')
        self.attacker = User.objects.create_user(
            email='attacker@jbnu.ac.kr', username='attacker',
            password='Password!1x', semester=1,
        )
        self.attacker.is_active = True; self.attacker.is_verified = True; self.attacker.save()
        self.victim = User.objects.create_user(
            email='victim@jbnu.ac.kr', username='victim',
            password='Password!1x', semester=1,
        )
        self.victim.is_active = True; self.victim.is_verified = True; self.victim.save()

    def _tokens(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token), str(refresh)

    def test_logout_rejects_foreign_refresh_token(self):
        """공격자가 자신의 access로 인증 후 피해자 refresh를 blacklist 시도하면 거부."""
        attacker_access, _ = self._tokens(self.attacker)
        _, victim_refresh = self._tokens(self.victim)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {attacker_access}')
        res = self.client.post(self.logout_url, {'refresh': victim_refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        # 피해자의 refresh는 여전히 유효해야 한다.
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
        from rest_framework_simplejwt.tokens import RefreshToken
        jti = RefreshToken(victim_refresh).get('jti')
        self.assertFalse(BlacklistedToken.objects.filter(token__jti=jti).exists())


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class TokenRefreshBlacklistTest(TestCase):
    """이미 blacklist된 refresh token으로는 재발급이 불가능해야 한다."""

    def setUp(self):
        self.client = APIClient()
        self.refresh_url = reverse('token_refresh')
        self.user = User.objects.create_user(
            email='blacklist@jbnu.ac.kr', username='bl',
            password='Password!1x', semester=1,
        )
        self.user.is_active = True; self.user.is_verified = True; self.user.save()

    def test_blacklisted_refresh_is_rejected(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user)
        refresh.blacklist()
        res = self.client.post(self.refresh_url, {'refresh': str(refresh)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class TokenRefreshGuardTest(TestCase):
    """리프레시 경로에서 비활성/미인증 계정은 차단되어야 한다."""

    def setUp(self):
        self.client = APIClient()
        self.refresh_url = reverse('token_refresh')
        self.user = User.objects.create_user(
            email='refresh@jbnu.ac.kr',
            username='refresh',
            password='Password!1x',
            semester=1,
        )
        self.user.is_active = True
        self.user.is_verified = True
        self.user.save()

    def _issue_refresh(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        return str(RefreshToken.for_user(self.user))

    def test_refresh_rejected_when_user_deactivated(self):
        refresh = self._issue_refresh()
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        response = self.client.post(self.refresh_url, {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_rejected_when_unverified(self):
        refresh = self._issue_refresh()
        self.user.is_verified = False
        self.user.save(update_fields=['is_verified'])
        response = self.client.post(self.refresh_url, {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(REST_FRAMEWORK=NO_THROTTLE_REST_FRAMEWORK)
class PublicProfileActivityVisibilityTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.target = User.objects.create_user(
            email='target@jbnu.ac.kr',
            username='target',
            password='Password!1x',
            semester=1,
        )
        self.target.is_active = True
        self.target.is_verified = True
        self.target.save()

        self.category = Category.objects.create(name='Cat')
        self.public_board = Board.objects.create(name='Public', category=self.category)
        self.staff_board = Board.objects.create(name='Staff', category=self.category)
        Board.objects.filter(pk=self.staff_board.pk).update(read_permission='staff')

        self.public_post = Post.objects.create(
            author=self.target,
            board=self.public_board,
            title='public visible',
            content_md='x',
            is_anonymous=False,
        )
        self.staff_only_post = Post.objects.create(
            author=self.target,
            board=self.public_board,
            title='staff secret',
            content_md='x',
            post_type=Post.PostType.STAFF_ONLY,
            is_anonymous=False,
        )
        self.staff_board_post = Post.objects.create(
            author=self.target,
            board=self.staff_board,
            title='board secret',
            content_md='x',
            is_anonymous=False,
        )
        Comment.objects.create(author=self.target, post=self.public_post, content='public comment', is_anonymous=False)
        Comment.objects.create(author=self.target, post=self.staff_only_post, content='staff comment', is_anonymous=False)
        Comment.objects.create(author=self.target, post=self.staff_board_post, content='board comment', is_anonymous=False)

    def _url(self):
        return reverse('public-profile', kwargs={'username': 'target'})

    def test_profile_omits_activity_until_requested(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['posts'], [])
        self.assertEqual(response.data['comments'], [])

    def test_activity_excludes_unreadable_posts_for_anonymous_user(self):
        response = self.client.get(self._url(), {'include_activity': '1'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['title'] for item in response.data['posts']], ['public visible'])
        self.assertEqual([item['content'] for item in response.data['comments']], ['public comment'])
