from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase
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


class UserEmailVerificationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup_url = reverse('signup')
        self.email_verify_url = reverse('email-verify')
        self.user_data = {
            'email': 'test@example.com',
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
        self.assertEqual(verify_response.data['error'], 'Invalid verification code.')

        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(user.is_verified)

    def test_email_verification_with_nonexistent_user(self):
        verify_data = {
            'email': 'nonexistent@example.com',
            'verifyCode': '123456',
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(verify_response.data['error'], 'User not found')


class PasswordResetFlowTest(TestCase):
    """비밀번호 재설정 플로우: DB에 저장된 opaque 토큰을 통해 인증을 강제한다."""

    def setUp(self):
        self.client = APIClient()
        self.verify_url = reverse('password-reset-verify')
        self.reset_url = reverse('password-reset')
        self.email = 'reset-me@example.com'
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

    def _verify(self):
        return self.client.post(
            self.verify_url,
            {'email': self.email, 'verification_code': self.raw_code},
            format='json',
        )

    def test_verify_creates_db_token_and_removes_code(self):
        response = self._verify()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        raw = response.data['reset_token']
        self.assertTrue(raw)
        self.assertEqual(response.data['expires_in'], RESET_TOKEN_TTL_SECONDS)

        # 인증코드는 reset 토큰 발급 후 바로 파기되어야 한다.
        self.assertFalse(EmailVerificationCode.objects.filter(user=self.user).exists())

        # 평문 토큰은 DB에 저장되지 않고 해시만 저장되어야 한다.
        record = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(record.token_hash, _hash(raw))
        self.assertNotIn(raw, record.token_hash)
        self.assertIsNone(record.used_at)
        self.assertGreater(record.expires_at, timezone.now())

    def test_verify_invalidates_previous_active_tokens(self):
        first = self._verify()
        # 재검증을 위해 인증코드를 다시 생성 (실서비스에선 재요청 플로우를 타지만 테스트 편의상 직접 생성)
        EmailVerificationCode.objects.create(
            user=self.user,
            code=make_password(self.raw_code),
        )
        second = self._verify()
        self.assertEqual(second.status_code, status.HTTP_200_OK)

        first_record = PasswordResetToken.objects.get(token_hash=_hash(first.data['reset_token']))
        self.assertIsNotNone(first_record.used_at)

        # 이전 토큰은 이제 사용 불가
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
            email='other@example.com',
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
        # raw 토큰 문자열이 DB 어디에도 평문으로 저장되지 않아야 한다.
        self.assertFalse(PasswordResetToken.objects.filter(token_hash=raw).exists())
        self.assertTrue(PasswordResetToken.objects.filter(token_hash=_hash(raw)).exists())
