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


class PostVisibilityHardeningTest(APITestCase):
    """Tier A 보안 강화: STAFF_ONLY/JUSTIFICATION 접근·post_type 조작·attachment 소유권."""

    def setUp(self):
        self.category = Category.objects.create(name='Cat')
        self.board = Board.objects.create(name='Gen', category=self.category)
        self.staff = User.objects.create_user(
            username='staff', email='staff@example.com', password='pw',
            is_verified=True, is_active=True, is_staff=True,
        )
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.attacker = User.objects.create_user(
            username='a', email='a@example.com', password='pw',
            is_verified=True, is_active=True,
        )

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

    def test_staff_only_post_hidden_from_regular_user(self):
        staff_post = Post.objects.create(
            author=self.staff, board=self.board,
            title='staff secret', content_md='x',
            post_type=Post.PostType.STAFF_ONLY,
        )
        self._auth(self.user)
        res = self.client.get(reverse('post-detail-update-destroy', kwargs={'post_id': staff_post.id}))
        self.assertIn(res.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_staff_only_post_visible_to_staff(self):
        staff_post = Post.objects.create(
            author=self.staff, board=self.board,
            title='staff secret', content_md='x',
            post_type=Post.PostType.STAFF_ONLY,
        )
        self._auth(self.staff)
        res = self.client.get(reverse('post-detail-update-destroy', kwargs={'post_id': staff_post.id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_post_type_cannot_be_changed_by_author(self):
        post = Post.objects.create(
            author=self.user, board=self.board,
            title='mine', content_md='x',
            post_type=Post.PostType.DEFAULT,
        )
        self._auth(self.user)
        url = reverse('post-detail-update-destroy', kwargs={'post_id': post.id})
        self.client.patch(url, {'post_type': Post.PostType.STAFF_ONLY}, format='json')
        post.refresh_from_db()
        self.assertEqual(post.post_type, Post.PostType.DEFAULT)

    def test_attachment_must_be_owned_by_requester(self):
        self._auth(self.attacker)
        url = reverse('post-list-create', kwargs={'board_id': self.board.id})
        victim_path = f"uploads/2025/01/01/{self.user.id}/abc.png"
        res = self.client.post(url, {
            'title': 'x',
            'content_md': 'y',
            'board_id': self.board.id,
            'attachment_paths': [{'path': victim_path, 'name': 'abc.png'}],
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_own_attachment_is_accepted(self):
        self._auth(self.user)
        url = reverse('post-list-create', kwargs={'board_id': self.board.id})
        own_path = f"uploads/2025/01/01/{self.user.id}/abc.png"
        res = self.client.post(url, {
            'title': 'x',
            'content_md': 'y',
            'board_id': self.board.id,
            'attachment_paths': [{'path': own_path, 'name': 'abc.png'}],
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
