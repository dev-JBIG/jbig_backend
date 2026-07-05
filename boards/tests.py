from rest_framework.test import APITestCase
from rest_framework import status
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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


class CategoryLatestPostTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.category = Category.objects.create(name='Cat')
        self.board = Board.objects.create(name='Public Board', category=self.category)

    def _category_boards(self):
        res = self.client.get(reverse('category-list-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('categories', res.data)
        category_data = next(
            item for item in res.data['categories']
            if item['category'] == self.category.name
        )
        return category_data['boards']

    def test_category_boards_include_latest_post_created_at(self):
        post = Post.objects.create(
            author=self.user,
            board=self.board,
            title='visible',
            content_md='x',
        )
        created_at = timezone.now().replace(microsecond=0)
        Post.objects.filter(pk=post.pk).update(created_at=created_at)

        boards = self._category_boards()

        board_data = next(item for item in boards if item['id'] == self.board.id)
        self.assertEqual(parse_datetime(board_data['latest_post_created_at']), created_at)

    def test_category_latest_post_does_not_expose_unreadable_posts(self):
        staff_post = Post.objects.create(
            author=self.user,
            board=self.board,
            title='staff only',
            content_md='x',
            post_type=Post.PostType.STAFF_ONLY,
        )
        Post.objects.filter(pk=staff_post.pk).update(created_at=timezone.now())

        staff_board = Board.objects.create(name='Staff Board', category=self.category)
        Board.objects.filter(pk=staff_board.pk).update(read_permission='staff')
        staff_board_post = Post.objects.create(
            author=self.user,
            board=staff_board,
            title='private board',
            content_md='x',
        )
        Post.objects.filter(pk=staff_board_post.pk).update(created_at=timezone.now())

        boards = self._category_boards()

        public_board = next(item for item in boards if item['id'] == self.board.id)
        private_board = next(item for item in boards if item['id'] == staff_board.id)
        self.assertIsNone(public_board['latest_post_created_at'])
        self.assertIsNone(private_board['latest_post_created_at'])


@override_settings(USE_LOCAL_STORAGE=True, MEDIA_URL='/media/')
class BoardPostOGPreviewTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='oguser', email='og@example.com', password='password123',
            is_verified=True, is_active=True,
        )
        self.category = Category.objects.create(name='OG Category')
        self.board = Board.objects.create(name='Public Board', category=self.category)

    def _url(self, board_id, post_id):
        return reverse('board-post-og', kwargs={'board_id': board_id, 'post_id': post_id})

    def _create_post(self, **kwargs):
        data = {
            'author': self.user,
            'board': self.board,
            'title': 'Public title',
            'content_md': '',
            'post_type': Post.PostType.DEFAULT,
        }
        data.update(kwargs)
        return Post.objects.create(**data)

    def assertDefaultOG(self, response):
        self.assertContains(response, '<meta property="og:title" content="JBIG">')
        self.assertContains(response, '<meta property="og:description" content="Data are profoundly dumb.">')
        self.assertContains(response, '<meta property="og:image" content="https://jbig.co.kr/JBIG-logo-1200x630.png">')

    def test_public_default_post_returns_post_title_and_jbig_description(self):
        post = self._create_post(title='Visible post')

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertEqual(response['Content-Type'], 'text/html; charset=utf-8')
        self.assertContains(response, '<meta property="og:title" content="Visible post">')
        self.assertContains(response, '<meta property="og:description" content="JBIG">')
        self.assertContains(response, '<meta name="twitter:card" content="summary_large_image">')

    def test_staff_only_post_falls_back_without_title(self):
        post = self._create_post(title='staff secret', post_type=Post.PostType.STAFF_ONLY)

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertDefaultOG(response)
        self.assertNotContains(response, 'staff secret')

    def test_justification_post_falls_back_without_title(self):
        post = self._create_post(title='justification secret', post_type=Post.PostType.JUSTIFICATION_LETTER)

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertDefaultOG(response)
        self.assertNotContains(response, 'justification secret')

    def test_staff_read_board_post_falls_back_without_title(self):
        staff_board = Board.objects.create(name='Staff Board', category=self.category)
        Board.objects.filter(id=staff_board.id).update(read_permission='staff')
        staff_board.refresh_from_db()
        post = self._create_post(board=staff_board, title='private board secret')

        response = self.client.get(self._url(staff_board.id, post.id))

        self.assertDefaultOG(response)
        self.assertNotContains(response, 'private board secret')

    def test_attachment_image_is_selected(self):
        post = self._create_post(
            content_md=f'![body](media-key://uploads/2026/01/01/{self.user.id}/body.jpg)',
            attachment_paths=[{
                'path': f'uploads/2026/01/01/{self.user.id}/attached.png',
                'name': 'attached.png',
            }],
        )

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertContains(
            response,
            f'<meta property="og:image" content="/media/uploads/2026/01/01/{self.user.id}/attached.png">',
        )
        self.assertNotContains(response, f'/media/uploads/2026/01/01/{self.user.id}/body.jpg')

    def test_markdown_image_is_selected(self):
        post = self._create_post(
            content_md=f'Intro\n\n![preview](media-key://uploads/2026/01/02/{self.user.id}/body.webp)',
        )

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertContains(
            response,
            f'<meta property="og:image" content="/media/uploads/2026/01/02/{self.user.id}/body.webp">',
        )

    def test_missing_image_falls_back_to_default_logo(self):
        post = self._create_post()

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertContains(response, '<meta property="og:image" content="https://jbig.co.kr/JBIG-logo-1200x630.png">')

    def test_title_is_html_escaped(self):
        post = self._create_post(title='<script>"&')

        response = self.client.get(self._url(self.board.id, post.id))

        self.assertContains(response, '<meta property="og:title" content="&lt;script&gt;&quot;&amp;">')
        self.assertNotContains(response, '<meta property="og:title" content="<script>"&">')

    def test_og_endpoint_does_not_increment_views(self):
        post = self._create_post(views=7)

        self.client.get(self._url(self.board.id, post.id))

        post.refresh_from_db()
        self.assertEqual(post.views, 7)

    def test_board_post_mismatch_falls_back_to_default_og(self):
        other_board = Board.objects.create(name='Other Board', category=self.category)
        post = self._create_post(title='wrong board title')

        response = self.client.get(self._url(other_board.id, post.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDefaultOG(response)
        self.assertNotContains(response, 'wrong board title')


class PostListPerformanceTest(APITestCase):
    """성능 회귀 방지 테스트.

    - 목록/상세 응답이 게시글·댓글 수에 상관없이 '일정한 쿼리 수'로 처리되는지
      검증(N+1 회귀 감지).
    - 목록 첨부 응답이 스토리지 head_object 없이 url+name 만 담는지(특성화) 검증.
    """

    def setUp(self):
        from .models import Category, Board, Post, Comment, PostLike
        self.category = Category.objects.create(name='Perf Category')
        self.board = Board.objects.create(name='Perf Board', category=self.category)
        self.user = User.objects.create_user(
            username='perfuser', email='perf@example.com', password='password123',
            is_verified=True, is_active=True,
        )

    def _make_posts(self, n, with_attachment=False):
        from .models import Post, Comment, PostLike
        for i in range(n):
            post = Post.objects.create(
                author=self.user, board=self.board, title=f'Perf Post {i}',
                content_md='body',
                attachment_paths=(
                    [{'path': 'uploads/sample.png', 'name': 'sample.png'}]
                    if with_attachment else []
                ),
            )
            Comment.objects.create(post=post, author=self.user, content='c')
            PostLike.objects.create(user=self.user, post=post)

    def test_list_query_count_does_not_grow_with_posts(self):
        """글이 3개 → 10개로 늘어도 목록 쿼리 수가 동일해야 한다(N+1 없음)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse('post-list-create', kwargs={'board_id': self.board.id})

        self._make_posts(3)
        with CaptureQueriesContext(connection) as ctx_small:
            res = self.client.get(url, {'page_size': 50})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['results']), 3)

        self._make_posts(7)  # 총 10개
        with CaptureQueriesContext(connection) as ctx_large:
            res = self.client.get(url, {'page_size': 50})
        self.assertEqual(len(res.data['results']), 10)

        self.assertEqual(
            len(ctx_small.captured_queries), len(ctx_large.captured_queries),
            f"목록에 N+1 회귀 발생: 3글={len(ctx_small.captured_queries)}쿼리, "
            f"10글={len(ctx_large.captured_queries)}쿼리",
        )

    def test_list_attachments_have_url_name_but_no_size(self):
        """특성화: 목록 첨부는 url+name 만 담고 size(head_object)는 담지 않는다."""
        self._make_posts(1, with_attachment=True)
        url = reverse('post-list-create', kwargs={'board_id': self.board.id})

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        attachments = res.data['results'][0]['attachment_paths']
        self.assertEqual(len(attachments), 1)
        entry = attachments[0]
        self.assertIn('url', entry)
        self.assertIn('name', entry)
        self.assertEqual(entry['name'], 'sample.png')
        self.assertNotIn('size', entry)  # 목록에서는 스토리지 왕복 없음

    def test_detail_comment_tree_query_count_does_not_grow(self):
        """댓글이 늘어도 상세 조회 쿼리 수가 동일해야 한다(댓글 트리 N+1 없음)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import Post, Comment

        post = Post.objects.create(
            author=self.user, board=self.board, title='Detail Perf', content_md='b',
        )
        url = reverse('post-detail-update-destroy', kwargs={'post_id': post.id})

        for i in range(2):
            Comment.objects.create(post=post, author=self.user, content=f'c{i}')
        with CaptureQueriesContext(connection) as ctx_small:
            self.client.get(url)

        for i in range(8):
            Comment.objects.create(post=post, author=self.user, content=f'more{i}')
        with CaptureQueriesContext(connection) as ctx_large:
            self.client.get(url)

        self.assertEqual(
            len(ctx_small.captured_queries), len(ctx_large.captured_queries),
            f"댓글 트리에 N+1 회귀 발생: 2댓글={len(ctx_small.captured_queries)}쿼리, "
            f"10댓글={len(ctx_large.captured_queries)}쿼리",
        )
