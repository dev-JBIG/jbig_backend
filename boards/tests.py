from unittest.mock import patch

from rest_framework.test import APITestCase
from rest_framework import status
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User
from .models import Board, Post, Category, Comment, Notification


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

    def test_post_detail_increments_views_with_atomic_update(self):
        post = Post.objects.create(
            author=self.user, board=self.board,
            title='Viewed Post', content_md='detail test content', views=7,
        )
        url = reverse('post-detail-update-destroy', kwargs={'post_id': post.id})

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['views'], 8)

        post.refresh_from_db()
        self.assertEqual(post.views, 8)

        post_selects = [
            query['sql']
            for query in queries.captured_queries
            if query['sql'].startswith('SELECT')
            and 'FROM "post"' in query['sql']
            and 'WHERE "post"."id"' in query['sql']
        ]
        self.assertEqual(len(post_selects), 1)

        atomic_view_updates = [
            query['sql']
            for query in queries.captured_queries
            if query['sql'].startswith('UPDATE "post"')
            and '"views" = ("post"."views" + 1)' in query['sql']
        ]
        self.assertEqual(len(atomic_view_updates), 1)

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


@override_settings(USE_LOCAL_STORAGE=True, MEDIA_URL='/media/')
class PostListPerformanceTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.other_user = User.objects.create_user(
            username='other', email='other@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.category = Category.objects.create(name='Cat')
        self.board = Board.objects.create(name='Board', category=self.category)

        token = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

    def test_default_list_omits_attachments_and_photo_view_keeps_url_name_without_head_object(self):
        file_key = f'uploads/2026/07/03/{self.user.id}/image.jpg'
        Post.objects.create(
            author=self.user,
            board=self.board,
            title='with attachment',
            content_md='x',
            attachment_paths=[{'path': file_key, 'name': 'image.jpg'}],
        )

        with patch('boards.serializers.get_s3_client') as get_s3_client:
            response = self.client.get(reverse('post-list-create', kwargs={'board_id': self.board.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        get_s3_client.assert_not_called()
        self.assertNotIn('attachment_paths', response.data['results'][0])

        with patch('boards.serializers.get_s3_client') as get_s3_client:
            response = self.client.get(
                reverse('post-list-create', kwargs={'board_id': self.board.id}),
                {'view': 'photo'},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        get_s3_client.assert_not_called()
        attachments = response.data['results'][0]['attachment_paths']
        self.assertEqual(attachments, [{'url': f'/media/{file_key}', 'name': 'image.jpg'}])
        self.assertNotIn('size', attachments[0])

    def test_list_counts_are_annotated_without_per_row_count_queries(self):
        post = Post.objects.create(
            author=self.user,
            board=self.board,
            title='counted',
            content_md='x',
        )
        post.likes.add(self.user, self.other_user)
        for idx in range(3):
            Comment.objects.create(post=post, author=self.other_user, content=f'comment {idx}')

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                reverse('post-list-create', kwargs={'board_id': self.board.id}),
                {'page_size': 10},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        self.assertEqual(item['likes_count'], 2)
        self.assertEqual(item['comment_count'], 3)

        per_row_count_queries = [
            query['sql']
            for query in queries.captured_queries
            if (
                'COUNT' in query['sql']
                and (
                    ('FROM "comment"' in query['sql'] and 'WHERE "comment"."post_id"' in query['sql'])
                    or ('FROM "post_like"' in query['sql'] and 'WHERE "post_like"."post_id"' in query['sql'])
                )
            )
        ]
        self.assertEqual(per_row_count_queries, [])

    def test_all_posts_list_keeps_private_boundaries(self):
        Post.objects.create(author=self.user, board=self.board, title='public', content_md='x')
        Post.objects.create(
            author=self.other_user,
            board=self.board,
            title='staff only',
            content_md='x',
            post_type=Post.PostType.STAFF_ONLY,
        )
        Post.objects.create(
            author=self.user,
            board=self.board,
            title='own justification',
            content_md='x',
            post_type=Post.PostType.JUSTIFICATION_LETTER,
        )
        Post.objects.create(
            author=self.other_user,
            board=self.board,
            title='other justification',
            content_md='x',
            post_type=Post.PostType.JUSTIFICATION_LETTER,
        )
        staff_board = Board.objects.create(name='Staff Board', category=self.category)
        Board.objects.filter(pk=staff_board.pk).update(read_permission='staff')
        Post.objects.create(author=self.other_user, board=staff_board, title='private board', content_md='x')

        response = self.client.get(reverse('all-posts-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = {item['title'] for item in response.data['results']}
        self.assertEqual(titles, {'public', 'own justification'})


class NotificationPerformanceTest(APITestCase):
    def setUp(self):
        self.recipient = User.objects.create_user(
            username='recipient', email='recipient@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.actor = User.objects.create_user(
            username='actor', email='actor@example.com', password='pw',
            is_verified=True, is_active=True,
        )
        self.category = Category.objects.create(name='Cat')
        self.board = Board.objects.create(name='Board', category=self.category)

        token = RefreshToken.for_user(self.recipient)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

    def _create_notification(self, idx, is_read=False):
        post = Post.objects.create(
            author=self.recipient,
            board=self.board,
            title=f'post {idx}',
            content_md='x',
        )
        comment = Comment.objects.create(
            post=post,
            author=self.actor,
            content=f'comment {idx}',
        )
        return Notification.objects.create(
            recipient=self.recipient,
            actor=self.actor,
            notification_type=Notification.NotificationType.COMMENT,
            post=post,
            comment=comment,
            is_read=is_read,
        )

    def test_notification_list_selects_related_objects(self):
        for idx in range(50):
            self._create_notification(idx)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('notification-list'), {'page_size': 50})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 50)

        related_lookup_queries = [
            query['sql']
            for query in queries.captured_queries
            if (
                ('FROM "post"' in query['sql'] and 'WHERE "post"."id"' in query['sql'])
                or ('FROM "board"' in query['sql'] and 'WHERE "board"."id"' in query['sql'])
                or ('FROM "comment"' in query['sql'] and 'WHERE "comment"."id"' in query['sql'])
                or (
                    'FROM "user"' in query['sql']
                    and f'WHERE "user"."id" = {self.actor.id}' in query['sql']
                )
            )
        ]
        self.assertEqual(related_lookup_queries, [])

    def test_unread_count_and_mark_read_are_unchanged(self):
        first = self._create_notification(1)
        self._create_notification(2)
        self._create_notification(3, is_read=True)

        response = self.client.get(reverse('notification-unread-count'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['unread_count'], 2)

        response = self.client.post(reverse('notification-mark-read', kwargs={'notification_id': first.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['success'], True)

        response = self.client.get(reverse('notification-unread-count'))
        self.assertEqual(response.data['unread_count'], 1)

        response = self.client.post(reverse('notification-mark-all-read'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['success'], True)

        response = self.client.get(reverse('notification-unread-count'))
        self.assertEqual(response.data['unread_count'], 0)


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

    def test_category_total_count_does_not_include_unreadable_posts(self):
        Post.objects.create(
            author=self.user,
            board=self.board,
            title='public',
            content_md='x',
        )
        Post.objects.create(
            author=self.user,
            board=self.board,
            title='staff only',
            content_md='x',
            post_type=Post.PostType.STAFF_ONLY,
        )
        staff_board = Board.objects.create(name='Staff Board', category=self.category)
        Board.objects.filter(pk=staff_board.pk).update(read_permission='staff')
        Post.objects.create(
            author=self.user,
            board=staff_board,
            title='private board',
            content_md='x',
        )

        res = self.client.get(reverse('category-list-list'))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_post_count'], 1)


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


class CommentTreeIsLikedPerfTest(APITestCase):
    """상세 댓글 트리의 isLiked 를 트리 전체 1쿼리로 선계산 → 댓글 수와
    무관하게 상세 조회 쿼리 수가 일정한지(N+1 회귀 감지) 검증."""

    def setUp(self):
        from .models import Category, Board, Post
        self.category = Category.objects.create(name='ItLike Cat')
        self.board = Board.objects.create(name='ItLike Board', category=self.category)
        self.user = User.objects.create_user(
            username='ituser', email='ituser@example.com', password='password123',
            is_verified=True, is_active=True,
        )
        token = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        self.post = Post.objects.create(
            author=self.user, board=self.board, title='ItLike', content_md='x',
        )
        self.url = reverse('post-detail-update-destroy', kwargs={'post_id': self.post.id})

    def _add_liked_comments(self, n):
        from .models import Comment, CommentLike
        for i in range(n):
            c = Comment.objects.create(post=self.post, author=self.user, content=f'c{i}')
            CommentLike.objects.create(user=self.user, comment=c)

    def test_detail_query_count_constant_with_comment_growth(self):
        self._add_liked_comments(2)
        with CaptureQueriesContext(connection) as ctx_small:
            self.client.get(self.url)

        self._add_liked_comments(8)  # 총 10개
        with CaptureQueriesContext(connection) as ctx_large:
            self.client.get(self.url)

        self.assertEqual(
            len(ctx_small.captured_queries), len(ctx_large.captured_queries),
            f"댓글 트리 isLiked N+1 회귀: 2댓글={len(ctx_small.captured_queries)}쿼리, "
            f"10댓글={len(ctx_large.captured_queries)}쿼리",
        )

    def test_isliked_values_are_correct(self):
        """일괄 계산이 정확한 값을 주는지: 내가 누른 댓글만 isLiked=True."""
        from .models import Comment, CommentLike
        liked = Comment.objects.create(post=self.post, author=self.user, content='liked')
        CommentLike.objects.create(user=self.user, comment=liked)
        not_liked = Comment.objects.create(post=self.post, author=self.user, content='not')

        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        by_id = {c['id']: c for c in res.data['comments']}
        self.assertTrue(by_id[liked.id]['isLiked'])
        self.assertFalse(by_id[not_liked.id]['isLiked'])
