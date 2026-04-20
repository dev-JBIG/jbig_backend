from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from users.models import EmailVerificationCode, PasswordResetToken, User
from users.password_reset_token import (
    RESET_TOKEN_TTL_SECONDS,
    _hash,
    issue_reset_token,
)


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
