from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from boards.models import Board, Category, Post
from .models import Recruitment


class RecruitmentBoardGateTest(APITestCase):
    """모집 API가 게시판 read_permission을 따라 게이트되는지 검증."""

    def setUp(self):
        self.member = User.objects.create_user(
            username='rmember', email='rmember@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.owner = User.objects.create_user(
            username='rowner', email='rowner@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.category = Category.objects.create(name='RecCat')
        self.member_board = Board.objects.create(
            name='회원모집', category=self.category, read_permission='member',
        )
        self.post = Post.objects.create(
            author=self.owner, board=self.member_board, title='모집글', content_md='x',
        )
        self.recruitment = Recruitment.objects.create(
            post=self.post, recruitment_type=Recruitment.RecruitmentType.STUDY,
        )

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

    def test_anonymous_cannot_see_recruitment_on_member_board(self):
        self.client.credentials()
        res = self.client.get(reverse('recruitment-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data['results'] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 0)
        res = self.client.get(reverse('recruitment-detail', kwargs={'post_id': self.post.id}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_member_can_see_and_apply_recruitment_on_member_board(self):
        self._auth(self.member)
        res = self.client.get(reverse('recruitment-detail', kwargs={'post_id': self.post.id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        res = self.client.post(
            reverse('recruitment-apply', kwargs={'post_id': self.post.id}),
            {'message': '지원합니다'}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_apply_recruitment_on_staff_board(self):
        Board.objects.filter(pk=self.member_board.pk).update(read_permission='staff')
        self._auth(self.member)
        res = self.client.get(reverse('recruitment-detail', kwargs={'post_id': self.post.id}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = self.client.post(
            reverse('recruitment-apply', kwargs={'post_id': self.post.id}),
            {'message': '지원합니다'}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
