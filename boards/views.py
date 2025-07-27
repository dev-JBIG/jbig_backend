from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAdminUser, IsAuthenticated
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema_view

from .models import Category, Board, Post, Comment, Attachment
from .serializers import (
    CategorySerializer, BoardSerializer, PostListSerializer, PostDetailSerializer,
    CommentSerializer, AttachmentSerializer
)
from .schemas import (
    category_viewset_schema, board_viewset_schema, post_viewset_schema,
    comment_viewset_schema, attachment_viewset_schema
)

@extend_schema_view(**category_viewset_schema)
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminUser]

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            self.permission_classes = [IsAuthenticatedOrReadOnly]
        return super().get_permissions()

@extend_schema_view(**board_viewset_schema)
class BoardViewSet(viewsets.ModelViewSet):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'list_posts']:
            self.permission_classes = [IsAuthenticatedOrReadOnly]
        else:
            self.permission_classes = [IsAdminUser]
        return super().get_permissions()

    @action(detail=True, methods=['get'], url_path='posts')
    def list_posts(self, request, pk=None):
        board = self.get_object()
        posts = Post.objects.filter(board=board).order_by('-created_at')
        
        page = self.paginate_queryset(posts)
        if page is not None:
            serializer = PostListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = PostListSerializer(posts, many=True, context={'request': request})
        return Response(serializer.data)

@extend_schema_view(**post_viewset_schema)
class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all().order_by('-created_at')
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action == 'list':
            return PostListSerializer
        return PostDetailSerializer

    def get_serializer_context(self):
        return {'request': self.request}

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.views += 1
        instance.save(update_fields=['views'])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        user = request.user

        if user in post.likes.all():
            post.likes.remove(user)
            liked = False
        else:
            post.likes.add(user)
            liked = True
        
        return Response({'liked': liked, 'likes_count': post.likes.count()})

@extend_schema_view(**comment_viewset_schema)
class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        post_id = self.request.data.get('post_id')
        post = get_object_or_404(Post, pk=post_id)
        parent_id = self.request.data.get('parent')
        parent = None
        if parent_id:
            parent = get_object_or_404(Comment, pk=parent_id)
        
        serializer.save(author=self.request.user, post=post, parent=parent)

    def get_queryset(self):
        qs = super().get_queryset()
        post_id = self.request.query_params.get('post_id')
        if post_id:
            return qs.filter(post_id=post_id, parent__isnull=True).order_by('created_at')
        return qs

@extend_schema_view(**attachment_viewset_schema)
class AttachmentViewSet(viewsets.ModelViewSet):
    queryset = Attachment.objects.all()
    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        files = request.FILES.getlist('file')
        attachments = []
        for file in files:
            attachment = Attachment.objects.create(file=file, filename=file.name)
            attachments.append(attachment)
        
        serializer = self.get_serializer(attachments, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)