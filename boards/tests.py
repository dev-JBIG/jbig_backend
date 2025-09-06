from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from users.models import User
from .models import Board, Post, Category
from django.core.files.uploadedfile import SimpleUploadedFile

class PostAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123', is_verified=True, is_active=True)
        self.category = Category.objects.create(name='Test Category')
        self.board = Board.objects.create(name='Test Board', category=self.category)
        self.client.login(email='test@example.com', password='password123') # Reverted to original login

    def test_post_create_and_list(self):
        # Test Post Creation
        url = reverse('post-list-create', kwargs={'board_id': self.board.id})
        data = {
            'title': 'Test Post',
            'content_html': '<html><body>test content for creation</body></html>', # Changed to string
            'board_id': self.board.id, # Added board ID
        }
        response = self.client.post(url, data, format='json') # Changed format to json
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(Post.objects.get().title, 'Test Post')

        # Test Post List
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_post_detail_view(self):
        # Changed content_html to a string
        post = Post.objects.create(author=self.user, board=self.board, title='Detail Test Post', content_html='<html><body>detail test content</body></html>')
        url = reverse('post-detail', kwargs={'post_id': post.id})

        response = self.client.get(url)
        # Removed print(response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['post_data']['title'], 'Detail Test Post')

    def test_post_update_board(self):
        # Create a second board
        second_board = Board.objects.create(name='Second Board', category=self.category)

        # Create a post in the initial board
        # Changed content_html to a string
        post = Post.objects.create(author=self.user, board=self.board, title='Post to Move', content_html='<html><body>original content for move</body></html>')
        
        # URL for updating the post
        url = reverse('post-detail', kwargs={'post_id': post.id})

        # Data to update the board
        update_data = {
            'board_id': second_board.id, # Changed from 'board' to 'board_id'
        }

        # Send PATCH request
        response = self.client.patch(url, update_data, format='json')

        # Assert status code
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert database change
        post.refresh_from_db()
        self.assertEqual(post.board.id, second_board.id)