from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet,
    BoardViewSet,
    PostViewSet,
    CommentViewSet,
    AttachmentViewSet,
)

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'boards', BoardViewSet, basename='board')
router.register(r'posts', PostViewSet, basename='post')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'attachments', AttachmentViewSet, basename='attachment')

urlpatterns = [
    path('', include(router.urls)),
]