from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from users.models import User
from .models import Board, Post

class PostAPITestCase(APITestCase):
    def setUp(self):
        # 1. 테스트용 사용자 생성
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        
        # 2. 테스트용 게시판 생성
        self.board = Board.objects.create(name='Test Board')

        # 3. JWT 토큰 발급 (로그인)
        response = self.client.post(reverse('token_obtain_pair'), {'email': 'test@example.com', 'password': 'password123'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.token = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_post_write(self):
        """
        게시글 생성 API (POST /api/post/write) 테스트
        """
        url = reverse('post-write')
        data = {
            'boardID': self.board.id,
            'text': 'This is a test post content.',
            'fileIDs': []
        }
        
        # API 요청
        response = self.client.post(url, data, format='json')
        
        # 응답 검증
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data, {'isUploaded': True})
        
        # DB 검증
        self.assertTrue(Post.objects.filter(board=self.board, author=self.user).exists())
        post = Post.objects.get(board=self.board, author=self.user)
        self.assertEqual(post.content, 'This is a test post content.')
        self.assertEqual(post.title, 'This is a test post') # content의 앞 20자

    def test_post_list(self):
        """
        게시글 목록 조회 API (GET /api/posts/) 테스트
        """
        # 테스트용 게시글 15개 생성
        for i in range(15):
            Post.objects.create(
                author=self.user,
                board=self.board,
                title=f'Test Post {i}',
                content=f'Content for test post {i}'
            )

        # 페이지네이션 테스트 (1페이지, 5개씩)
        url = reverse('post-list') + f'?boardID={self.board.id}&pageNum=1&perPage=5'
        response = self.client.get(url, format='json')

        # 응답 검증
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)
        self.assertEqual(response.data[0]['title'], 'Test Post 14') # 최신순 정렬 확인

        # 페이지네이션 테스트 (3페이지, 5개씩)
        url = reverse('post-list') + f'?boardID={self.board.id}&pageNum=3&perPage=5'
        response = self.client.get(url, format='json')

        # 응답 검증
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)
        self.assertEqual(response.data[0]['title'], 'Test Post 4')

    def test_post_list_invalid_board(self):
        """
        유효하지 않은 boardID로 목록 조회 시 400 에러 테스트
        """
        url = reverse('post-list') # boardID 없이 요청
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)