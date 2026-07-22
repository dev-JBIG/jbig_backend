from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BoardListViewSet,
    BoardListAPIView,
    AdminBoardListAPIView,
    AdminBoardUpdateAPIView,
    PostListCreateAPIView,
    PostRetrieveUpdateDestroyAPIView,
    CommentListCreateAPIView,
    CommentUpdateDestroyAPIView,
    AllPostListAPIView,
    PostSearchView,
    AllPostSearchView,
    PostAttachmentDownloadView,
    MediaStreamView,
    PostLikeAPIView,
    CommentLikeAPIView,
    BoardDetailAPIView,
    NotificationListAPIView,
    NotificationUnreadCountAPIView,
    NotificationMarkReadAPIView,
    DraftRetrieveCreateAPIView,
    DraftDeleteAPIView,
    board_post_og_preview,
)

router = DefaultRouter()
router.register(r'categories', BoardListViewSet, basename='category-list')

urlpatterns = [
    path('', include(router.urls)),
    path('boards/', BoardListAPIView.as_view(), name='board-list'),
    # 관리자 게시판 관리 (스태프 전용)
    path('admin/boards/', AdminBoardListAPIView.as_view(), name='admin-board-list'),
    path('admin/boards/<int:board_id>/', AdminBoardUpdateAPIView.as_view(), name='admin-board-update'),
    path('boards/<int:board_id>/', BoardDetailAPIView.as_view(), name='board-detail'),
    path('boards/<int:board_id>/posts/', PostListCreateAPIView.as_view(), name='post-list-create'),
    path('og/board/<int:board_id>/<int:post_id>/', board_post_og_preview, name='board-post-og'),
    path('boards/<int:board_id>/search/', PostSearchView.as_view(), name='post-search-in-board'),
    path('posts/all/', AllPostListAPIView.as_view(), name='all-posts-list'),
    path('posts/all/search/', AllPostSearchView.as_view(), name='post-search-all'),
    path('posts/<int:post_id>/', PostRetrieveUpdateDestroyAPIView.as_view(), name='post-detail-update-destroy'),
    path('posts/<int:post_id>/attachments/<int:index>/download/', PostAttachmentDownloadView.as_view(), name='post-attachment-download'),
    # 본문 인라인 이미지: 서명 토큰으로 게이트된 스트리밍(최종 URL: /api/media/stream/?token=...)
    path('media/stream/', MediaStreamView.as_view(), name='media-stream'),
    path('posts/<int:post_id>/like/', PostLikeAPIView.as_view(), name='post-like'),
    path('posts/<int:post_id>/comments/', CommentListCreateAPIView.as_view(), name='comment-list-create'),
    path('comments/<int:comment_id>/', CommentUpdateDestroyAPIView.as_view(), name='comment-detail-update-destroy'),
    path('comments/<int:comment_id>/like/', CommentLikeAPIView.as_view(), name='comment-like'),
    # 알림 API
    path('notifications/', NotificationListAPIView.as_view(), name='notification-list'),
    path('notifications/unread-count/', NotificationUnreadCountAPIView.as_view(), name='notification-unread-count'),
    path('notifications/mark-read/', NotificationMarkReadAPIView.as_view(), name='notification-mark-all-read'),
    path('notifications/<int:notification_id>/mark-read/', NotificationMarkReadAPIView.as_view(), name='notification-mark-read'),
    # 임시저장 버퍼 API
    path('draft/', DraftRetrieveCreateAPIView.as_view(), name='draft-retrieve-create'),
    path('draft/delete/', DraftDeleteAPIView.as_view(), name='draft-delete'),
]
