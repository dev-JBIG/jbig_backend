from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User
from .models import Board, Post, Category


class PostAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='password123',
            is_verified=True, is_active=True,
        )
        self.category = Category.objects.create(name='Test Category')
        self.board = Board.objects.create(name='Test Board', category=self.category)
        # JWT 인증
        token = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

    def test_post_create_and_list(self):
        url = reverse('post-list-create', kwargs={'board_id': self.board.id})
        data = {
            'title': 'Test Post',
            'content_md': '## test content for creation',
            'board_id': self.board.id,
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(Post.objects.get().title, 'Test Post')

        # Test Post List
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_post_detail_view(self):
        post = Post.objects.create(
            author=self.user, board=self.board,
            title='Detail Test Post', content_md='detail test content',
        )
        url = reverse('post-detail-update-destroy', kwargs={'post_id': post.id})

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Detail Test Post')

    def test_post_update_board(self):
        second_board = Board.objects.create(name='Second Board', category=self.category)
        post = Post.objects.create(
            author=self.user, board=self.board,
            title='Post to Move', content_md='original content for move',
        )
        url = reverse('post-detail-update-destroy', kwargs={'post_id': post.id})

        response = self.client.patch(url, {'board_id': second_board.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        post.refresh_from_db()
        self.assertEqual(post.board.id, second_board.id)
