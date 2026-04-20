from datetime import datetime, timedelta, timezone as dt_timezone

import jwt
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from users.models import EmailVerificationCode, User
from users.password_reset_token import (
    RESET_TOKEN_ALGORITHM,
    RESET_TOKEN_PURPOSE,
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
            'semester': 1,  # Added semester
        }

    @patch('users.serializers.send_mail')
    def test_email_verification_flow(self, mock_send_mail):
        # 1. Sign up a user
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)

        # Check that the email was called
        mock_send_mail.assert_called_once()
        # Get the code from the mocked call
        message = mock_send_mail.call_args[0][1]
        sent_code = message.split(" ")[-1]

        # Retrieve the user
        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(user.is_verified)

        # 2. Verify email with the correct code
        verify_data = {
            'email': self.user_data['email'],
            'verifyCode': sent_code
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertEqual(verify_response.data['message'], 'Email verified successfully.')

        # 3. Check if is_verified is True
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

        # 4. Check that the verification code object is deleted
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())

    @patch('users.serializers.send_mail')
    def test_email_verification_with_invalid_code(self, mock_send_mail):
        # 1. Sign up a user
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)

        # 2. Attempt to verify with an invalid code
        verify_data = {
            'email': self.user_data['email'],
            'verifyCode': '123456'  # Invalid code
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(verify_response.data['error'], 'Invalid verification code.')

        # 3. Check that is_verified remains False
        user = User.objects.get(email=self.user_data['email'])
        self.assertFalse(user.is_verified)

    def test_email_verification_with_nonexistent_user(self):
        verify_data = {
            'email': 'nonexistent@example.com',
            'verifyCode': '123456'
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(verify_response.data['error'], 'User not found')


class PasswordResetFlowTest(TestCase):
    """비밀번호 재설정 플로우의 토큰 기반 인증을 검증한다."""

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

    def _reset_payload(self, token, email=None):
        return {
            'email': email or self.email,
            'reset_token': token,
            'new_password1': self.new_password,
            'new_password2': self.new_password,
        }

    def test_verify_returns_reset_token(self):
        response = self.client.post(
            self.verify_url,
            {'email': self.email, 'verification_code': self.raw_code},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('reset_token', response.data)
        self.assertGreater(len(response.data['reset_token']), 0)
        self.assertEqual(response.data['expires_in'], 600)

        payload = jwt.decode(
            response.data['reset_token'],
            settings.SECRET_KEY,
            algorithms=[RESET_TOKEN_ALGORITHM],
        )
        self.assertEqual(payload['sub'], self.email)
        self.assertEqual(payload['purpose'], RESET_TOKEN_PURPOSE)

    def test_reset_succeeds_with_valid_token(self):
        verify_response = self.client.post(
            self.verify_url,
            {'email': self.email, 'verification_code': self.raw_code},
            format='json',
        )
        token = verify_response.data['reset_token']

        response = self.client.post(self.reset_url, self._reset_payload(token), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(EmailVerificationCode.objects.filter(user=self.user).exists())

    def test_reset_without_token_rejected(self):
        """이전 단계 토큰 없이 비밀번호 재설정 시도는 거부되어야 한다 (핵심 취약점 방지)."""
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
            self._reset_payload('not-a-real-jwt'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_with_token_for_different_email_rejected(self):
        token_for_other = issue_reset_token('attacker@example.com')
        response = self.client.post(
            self.reset_url,
            self._reset_payload(token_for_other),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_with_expired_token_rejected(self):
        now = datetime.now(dt_timezone.utc)
        expired_payload = {
            'sub': self.email,
            'purpose': RESET_TOKEN_PURPOSE,
            'iat': int((now - timedelta(hours=2)).timestamp()),
            'exp': int((now - timedelta(hours=1)).timestamp()),
            'jti': 'expired-token',
        }
        expired_token = jwt.encode(
            expired_payload,
            settings.SECRET_KEY,
            algorithm=RESET_TOKEN_ALGORITHM,
        )
        response = self.client.post(
            self.reset_url,
            self._reset_payload(expired_token),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_with_wrong_purpose_rejected(self):
        """유효한 서명이지만 purpose가 다른 JWT는 재설정에 사용할 수 없어야 한다."""
        now = datetime.now(dt_timezone.utc)
        other_payload = {
            'sub': self.email,
            'purpose': 'something_else',
            'iat': int(now.timestamp()),
            'exp': int((now + timedelta(minutes=10)).timestamp()),
            'jti': 'wrong-purpose',
        }
        other_token = jwt.encode(
            other_payload,
            settings.SECRET_KEY,
            algorithm=RESET_TOKEN_ALGORITHM,
        )
        response = self.client.post(
            self.reset_url,
            self._reset_payload(other_token),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_reset_token_is_single_use(self):
        """한 번 성공한 토큰은 재사용해서 또 비밀번호를 바꿀 수 없어야 한다."""
        verify_response = self.client.post(
            self.verify_url,
            {'email': self.email, 'verification_code': self.raw_code},
            format='json',
        )
        token = verify_response.data['reset_token']

        first = self.client.post(self.reset_url, self._reset_payload(token), format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second_password = 'ThirdPassword!3'
        second = self.client.post(
            self.reset_url,
            {
                'email': self.email,
                'reset_token': token,
                'new_password1': second_password,
                'new_password2': second_password,
            },
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(second_password))

    def test_reset_without_prior_verification_code_rejected(self):
        """인증 코드 요청 없이 바로 위조 토큰을 만들어 보내도 거부되어야 한다."""
        EmailVerificationCode.objects.filter(user=self.user).delete()
        token = issue_reset_token(self.email)
        response = self.client.post(self.reset_url, self._reset_payload(token), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))
