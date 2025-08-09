from rest_framework import generics, status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import Board, Post, Comment, Category, Attachment
from .serializers import (
    BoardSerializer, PostListSerializer, PostDetailSerializer, PostCreateUpdateSerializer,
    CommentSerializer, CategoryWithBoardsSerializer, AttachmentSerializer
)
from .permissions import IsOwnerOrReadOnly, IsVerified

@extend_schema(tags=['Categories'])
@extend_schema_view(
    list=extend_schema(
        summary="카테고리별 게시판 목록 조회",
        description="모든 카테고리와 해당 카테고리에 속한 게시판 목록을 조회합니다.",
    )
)
class BoardListViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        categories = Category.objects.prefetch_related('boards').all()
        serializer = CategoryWithBoardsSerializer(categories, many=True)
        return Response(serializer.data)

@extend_schema(tags=['Boards'])
@extend_schema_view(
    get=extend_schema(
        summary="전체 게시판 목록 조회",
        description="사이트의 모든 게시판 목록을 조회합니다.",
    )
)
class BoardListAPIView(generics.ListAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    permission_classes = [AllowAny]

@extend_schema(tags=['Posts'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 목록 조회",
        description="특정 게시판에 속한 모든 게시글 목록을 조회합니다.",
    ),
    post=extend_schema(
        summary="게시글 생성",
        description="특정 게시판에 새로운 게시글을 작성합니다.",
    )
)
class PostListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PostCreateUpdateSerializer
        return PostListSerializer

    def get_queryset(self):
        board_id = self.kwargs.get('board_id')
        return Post.objects.filter(board_id=board_id).order_by('-created_at')

    def perform_create(self, serializer):
        board = get_object_or_404(Board, pk=self.kwargs.get('board_id'))
        serializer.save(author=self.request.user, board=board)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        instance = serializer.instance
        list_serializer = PostListSerializer(instance)
        
        headers = self.get_success_headers(list_serializer.data)
        return Response(list_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

@extend_schema(tags=['Posts'])
@extend_schema_view(
    get=extend_schema(summary="게시글 상세 조회"),
    put=extend_schema(summary="게시글 수정"),
    patch=extend_schema(summary="게시글 부분 수정"),
    delete=extend_schema(summary="게시글 삭제")
)
class PostRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Post.objects.all()
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    lookup_url_kwarg = 'post_id'

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return PostCreateUpdateSerializer
        return PostDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.views += 1
        instance.save(update_fields=['views'])
        
        post_serializer = self.get_serializer(instance)
        user = request.user

        is_admin = False
        if user.is_authenticated and hasattr(user, 'role') and user.role:
            is_admin = user.role.name == 'admin'

        response_data = {
            "post_data": post_serializer.data,
            "isTokenValid": user.is_authenticated,
            "isAdmin": is_admin if user.is_authenticated else False,
            "username": user.username if user.is_authenticated else None,
            "email": user.email if user.is_authenticated else None,
        }
        
        return Response(response_data)

@extend_schema(tags=['Comments'])
@extend_schema_view(
    get=extend_schema(summary="댓글 목록 조회"),
    post=extend_schema(summary="댓글 생성")
)
class CommentListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        post_id = self.kwargs.get('post_id')
        return Comment.objects.filter(post_id=post_id, parent__isnull=True).order_by('created_at')

    def perform_create(self, serializer):
        post = get_object_or_404(Post, pk=self.kwargs.get('post_id'))
        serializer.save(author=self.request.user, post=post)

@extend_schema(tags=['Comments'])
@extend_schema_view(
    put=extend_schema(summary="댓글 수정"),
    patch=extend_schema(summary="댓글 부분 수정"),
    delete=extend_schema(summary="댓글 삭제")
)
class CommentUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsOwnerOrReadOnly]
    lookup_url_kwarg = 'comment_id'

@extend_schema(tags=['Attachments'])
@extend_schema_view(
    post=extend_schema(
        summary="File 첨부",
        description="새로운 파일을 서버에 업로드합니다. 업로드 성공 시 첨부파일의 ID와 URL을 반환합니다.",
    )
)
class AttachmentCreateAPIView(generics.CreateAPIView):
    queryset = Attachment.objects.all()
    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        serializer.save(filename=self.request.data.get('file').name)