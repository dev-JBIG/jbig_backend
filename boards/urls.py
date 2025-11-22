from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BoardListViewSet,
    BoardListAPIView,
    PostListCreateAPIView,
    PostRetrieveUpdateDestroyAPIView,
    CommentListCreateAPIView,
    CommentUpdateDestroyAPIView,
    AllPostListAPIView,
    PostSearchView,
    AllPostSearchView,
    PostLikeAPIView,
    BoardDetailAPIView,
)

router = DefaultRouter()
router.register(r'categories', BoardListViewSet, basename='category-list')

urlpatterns = [
    path('', include(router.urls)),
    path('boards/', BoardListAPIView.as_view(), name='board-list'),
    path('boards/<int:board_id>/', BoardDetailAPIView.as_view(), name='board-detail'),
    path('boards/<int:board_id>/posts/', PostListCreateAPIView.as_view(), name='post-list-create'),
    path('boards/<int:board_id>/search/', PostSearchView.as_view(), name='post-search-in-board'),
    path('posts/all/', AllPostListAPIView.as_view(), name='all-posts-list'),
    path('posts/all/search/', AllPostSearchView.as_view(), name='post-search-all'),
    path('posts/<int:post_id>/', PostRetrieveUpdateDestroyAPIView.as_view(), name='post-detail-update-destroy'),
    path('posts/<int:post_id>/like/', PostLikeAPIView.as_view(), name='post-like'),
    path('posts/<int:post_id>/comments/', CommentListCreateAPIView.as_view(), name='comment-list-create'),
    path('comments/<int:comment_id>/', CommentUpdateDestroyAPIView.as_view(), name='comment-detail-update-destroy'),
]
