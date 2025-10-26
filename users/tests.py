from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import User, EmailVerificationCode
from unittest.mock import patch

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
            'verifyCode': '123456' # Invalid code
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
