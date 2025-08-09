import os
from rest_framework import generics, status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import Board, Post, Comment, Category, Attachment
from .serializers import (
    BoardSerializer, PostListSerializer, PostDetailSerializer, PostCreateUpdateSerializer,
    CommentSerializer, CategoryWithBoardsSerializer, AttachmentSerializer, PostDetailResponseSerializer,
    CategoryListResponseSerializer
)
from .permissions import IsOwnerOrReadOnly, IsVerified

@extend_schema(tags=['Categories'])
@extend_schema_view(
    list=extend_schema(
        summary="카테고리별 게시판 목록 조회",
        description="모든 카테고리와 해당 카테고리에 속한 게시판 목록을 조회합니다. 응답의 최상단에는 전체 게시글의 수가 포함됩니다.",
        responses={200: CategoryListResponseSerializer}
    )
)
class BoardListViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        total_post_count = Post.objects.count()
        categories = Category.objects.prefetch_related('boards').all()
        
        response_payload = {
            "total_post_count": total_post_count,
            "categories": categories
        }
        serializer = CategoryListResponseSerializer(response_payload)
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
    get=extend_schema(
        summary="게시글 상세 조회",
        description="""게시글의 상세 정보를 조회합니다. 인증된 사용자의 경우, 다음과 같은 추가 정보가 반환됩니다.
- `isTokenValid`: 토큰 유효 여부 (항상 true)
- `isAdmin`: 관리자 여부
- `username`: 사용자 이름
- `email`: 사용자 이메일""",
        responses={200: PostDetailResponseSerializer}
    ),
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
        return PostDetailResponseSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # 조회수 증가
        instance.views += 1
        instance.save(update_fields=['views'])
        
        user = request.user
        
        # 관리자 여부 확인 (기존 로직 유지)
        is_admin = False
        if hasattr(user, 'role') and user.role:
            is_admin = user.role.name == 'admin'

        # Serializer에 전달할 데이터 구조화
        response_data = {
            'post_data': instance,
            'isTokenValid': True,  # IsAuthenticated 통과 시 항상 유효
            'isAdmin': is_admin,
            'username': user.username,
            'email': user.email,
        }
        
        # PostDetailResponseSerializer를 사용하여 직렬화
        serializer = self.get_serializer(response_data)
        return Response(serializer.data)

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
        description="""새로운 파일을 서버에 업로드합니다. ��로드 성공 시 첨부파일의 ID와 URL을 반환합니다.
- 허용되는 확장자: .jpg, .png, .jpeg
- 파일당 최대 크기는 20MB로 제한됩니다.""",
    )
)
class AttachmentCreateAPIView(generics.CreateAPIView):
    queryset = Attachment.objects.all()
    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        file = request.data.get('file')
        if not file:
            return Response(
                {"error": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 확장자 검사
        allowed_extensions = ['.jpg', '.png', '.jpeg', '.hwp', '.hwpx', '.pdf', '.ppt', '.xlsx']
        file_extension = os.path.splitext(file.name)[1].lower()
        if file_extension not in allowed_extensions:
            return Response(
                {"error": f"File type not allowed. Allowed extensions are: {', '.join(allowed_extensions)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 파일 크기 검사
        if file.size > 20 * 1024 * 1024:  # 20MB
            return Response(
                {"error": "File size cannot exceed 20MB."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(filename=self.request.data.get('file').name)

@extend_schema(tags=['Posts'])
@extend_schema_view(
    get=extend_schema(
        summary="전체 게시글 목록 조회",
        description="모든 게시판의 게시글 목록을 조회합니다.",
    )
)
class AllPostListAPIView(generics.ListAPIView):
    queryset = Post.objects.all().order_by('-created_at')
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]