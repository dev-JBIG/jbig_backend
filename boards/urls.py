from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BoardListViewSet,
    BoardListAPIView,
    PostListCreateAPIView,
    PostRetrieveUpdateDestroyAPIView,
    CommentListCreateAPIView,
    CommentUpdateDestroyAPIView,
    AttachmentCreateAPIView,
)

router = DefaultRouter()
router.register(r'categories', BoardListViewSet, basename='category-list')

urlpatterns = [
    path('', include(router.urls)),
    path('boards/', BoardListAPIView.as_view(), name='board-list'),
    path('boards/<int:board_id>/posts/', PostListCreateAPIView.as_view(), name='post-list-create'),
    path('posts/<int:post_id>/', PostRetrieveUpdateDestroyAPIView.as_view(), name='post-detail'),
    path('posts/<int:post_id>/comments/', CommentListCreateAPIView.as_view(), name='comment-list-create'),
    path('comments/<int:comment_id>/', CommentUpdateDestroyAPIView.as_view(), name='comment-detail'),
    path('attachment/', AttachmentCreateAPIView.as_view(), name='attachment-create'),
]
