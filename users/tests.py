from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import User

class UserEmailVerificationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup_url = reverse('signup')
        self.email_verify_url = reverse('email-verify')
        self.user_data = {
            'email': 'test@example.com',
            'username': 'testuser',
            'password': 'testpassword123',
        }

    def test_email_verification_sets_is_wait_to_false(self):
        # 1. Sign up a user
        signup_response = self.client.post(self.signup_url, self.user_data, format='json')
        self.assertEqual(signup_response.status_code, status.HTTP_201_CREATED)
        
        # Retrieve the user to get the verification code
        user = User.objects.get(email=self.user_data['email'])
        self.assertTrue(user.is_wait) # Should be True after signup
        self.assertFalse(user.is_verified) # Should be False after signup
        self.assertTrue(user.is_active) # Should be True after signup

        # 2. Verify email with the correct code
        verify_data = {
            'email': self.user_data['email'],
            'verifyCode': user.verification_code
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_response.data['isVerified'])

        # 3. Check if is_wait is set to False and is_verified is True
        user.refresh_from_db()
        self.assertFalse(user.is_wait) # Should be False after verification
        self.assertTrue(user.is_verified) # Should be True after verification
        self.assertTrue(user.is_active) # Should remain True
        self.assertIsNone(user.verification_code) # Code should be cleared

    def test_email_verification_with_invalid_code(self):
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
        self.assertFalse(verify_response.data['isVerified'])

        # 3. Check that is_wait and is_verified remain unchanged
        user = User.objects.get(email=self.user_data['email'])
        self.assertTrue(user.is_wait)
        self.assertFalse(user.is_verified)
        self.assertTrue(user.is_active)

    def test_email_verification_with_nonexistent_user(self):
        verify_data = {
            'email': 'nonexistent@example.com',
            'verifyCode': '123456'
        }
        verify_response = self.client.post(self.email_verify_url, verify_data, format='json')
        self.assertEqual(verify_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', verify_response.data)
        self.assertEqual(verify_response.data['error'], 'User not found')