import os
from rest_framework import generics, status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, Q
from bs4 import BeautifulSoup

from .models import Board, Post, Comment, Category, Attachment
from .serializers import (
    BoardSerializer, PostListSerializer, PostDetailSerializer, PostCreateUpdateSerializer,
    CommentSerializer, CategoryWithBoardsSerializer, AttachmentSerializer, PostDetailResponseSerializer,
    CategoryListResponseSerializer, PostListResponseSerializer
)
from .permissions import (
    IsOwnerOrReadOnly,
    IsBoardReadable,
    IsPostWritable,
    IsCommentWritable,
    PostDetailPermission
)

@extend_schema(
    tags=['게시글'],
    summary="게시글 좋아요/취소",
    description="특정 게시글에 좋아요를 추가하거나 취소합니다. 이미 좋아요를 누른 상태에서 요청하면 좋아요가 취소됩니다."
)
class PostLikeAPIView(generics.GenericAPIView):
    queryset = Post.objects.all()
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = 'post_id'

    def post(self, request, *args, **kwargs):
        post = self.get_object()
        user = request.user

        try:
            like = post.likes.through.objects.get(user=user, post=post)
            like.delete()
            is_liked = False
        except post.likes.through.DoesNotExist:
            post.likes.add(user)
            is_liked = True

        likes_count = post.likes.count()
        return Response({'likes_count': likes_count, 'is_liked': is_liked}, status=status.HTTP_200_OK)


@extend_schema(
    tags=['게시글'],
    summary="게시글 검색",
    description="제목, 내용, 작성자명을 기준으로 게시글을 검색합니다. 사용자의 권한에 따라 접근 가능한 게시글 내에서만 검색이 수행됩니다.",
    parameters=[
        OpenApiParameter(
            name='q',
            description='검색할 키워드',
            required=True,
            type=str,
            location=OpenApiParameter.QUERY
        ),
    ]
)
class PostSearchView(generics.ListAPIView):
    serializer_class = PostListSerializer

    def get_queryset(self):
        query = self.request.query_params.get('q', None)
        if not query:
            return Post.objects.none()

        board_id = self.kwargs.get('board_id', None)
        user = self.request.user

        if board_id:
            board = get_object_or_404(Board, id=board_id)
            if board.read_permission == 'staff' and not (user.is_authenticated and user.is_staff):
                return Post.objects.none()
            base_queryset = Post.objects.filter(board_id=board_id)
        else:
            base_queryset = Post.objects.all()
            if not (user.is_authenticated and user.is_staff):
                base_queryset = base_queryset.filter(board__read_permission='all')

        queryset = base_queryset.visible_for_user(user)

        search_query = SearchQuery(query, search_type='websearch')
        search_filter = Q(search_vector=search_query) | Q(author__username__icontains=query)
        
        queryset = queryset.annotate(
            rank=SearchRank(F('search_vector'), search_query)
        ).filter(search_filter).order_by('-rank', '-created_at')

        return queryset

@extend_schema(
    tags=['게시글'],
    summary="전체 게시글 검색",
    description="모든 게시판의 게시글을 대상으로 검색합니다. 사용자의 권한에 따라 접근 가능한 게시글 내에서만 검색이 수행됩니다.",
    parameters=[
        OpenApiParameter(
            name='q',
            description='검색할 키워드',
            required=True,
            type=str,
            location=OpenApiParameter.QUERY
        ),
    ]
)
class AllPostSearchView(PostSearchView):
    def get_queryset(self):
        self.kwargs['board_id'] = None
        return super().get_queryset()


@extend_schema(tags=['게시판'])
@extend_schema_view(
    list=extend_schema(
        summary="카테고리별 게시판 목록 조회",
        description="모든 카테고리와 해당 카테고리에 속한 게시판 목록을 조회합니다. 응답의 최상단에는 전체 게시글의 수가 포함됩니다.",
        responses={200: CategoryListResponseSerializer},
    )
)
class BoardListViewSet(viewsets.ViewSet):
    def list(self, request, *args, **kwargs):
        total_post_count = Post.objects.count()
        categories = Category.objects.prefetch_related('boards').all()
        response_payload = {
            "total_post_count": total_post_count,
            "categories": categories
        }
        serializer = CategoryListResponseSerializer(response_payload)
        return Response(serializer.data)

@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="전체 게시판 목록 조회",
        description="사이트의 모든 게시판 목록을 조회합니다.",
    )
)
class BoardListAPIView(generics.ListAPIView):
    serializer_class = BoardSerializer
    
    def get_queryset(self):
        return Board.objects.all()


@extend_schema(tags=['게시글'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 목록 조회",
        description="""특정 게시판의 정보 및 게시글 목록을 조회합니다.\n- **게시판 접근 권한**: 게시판의 `read_permission` 설정에 따라 접근이 제어됩니다.\n- **게시글 필터링**: 사용자의 권한(스태프, 인증 여부)에 따라 조회되는 게시글이 자동으로 필터링됩니다. (예: 스태프 전용 글, 본인 작성 해명글 등) """,
        responses={
            200: PostListResponseSerializer,
            403: OpenApiResponse(description="게시판에 대한 읽기 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시판입니다."),
        },
    ),
    post=extend_schema(
        summary="게시글 생성",
        description="""특정 게시판에 새로운 게시글을 작성합니다.\n- **권한 (Board Level)**: 게시판의 `post_permission` 설정에 따라 접근이 제어됩니다.\n  - `all`: 인증된 사용자 누구나 작성 가능\n  - `staff`: 스태프만 작성 가능""",
        request=PostCreateUpdateSerializer,
        responses={
            201: PostListSerializer,
            400: OpenApiResponse(description="잘못된 요청 데이터입니다."),
            403: OpenApiResponse(description="게시판에 대한 쓰기 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시판입니다."),
        },
    )
)
class PostListCreateAPIView(generics.ListCreateAPIView):
    lookup_url_kwarg = 'board_id'

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsBoardReadable()]
        elif self.request.method == 'POST':
            return [IsPostWritable()]
        return [AllowAny()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PostCreateUpdateSerializer
        return PostListSerializer

    def get_queryset(self):
        board_id = self.kwargs.get('board_id')
        return Post.objects.filter(board_id=board_id).visible_for_user(self.request.user).order_by('-created_at')

    def get_object(self):
        board_id = self.kwargs.get(self.lookup_url_kwarg)
        obj = get_object_or_404(Board, pk=board_id)
        self.check_object_permissions(self.request, obj)
        return obj

    def list(self, request, *args, **kwargs):
        board = self.get_object()
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            response_data = {
                'board': BoardSerializer(board, context={'request': request}).data,
                'count': paginated_response.data['count'],
                'next': paginated_response.data['next'],
                'previous': paginated_response.data['previous'],
                'posts': paginated_response.data['results']
            }
            return Response(response_data)

        serializer = self.get_serializer(queryset, many=True)
        response_data = {
            'board': BoardSerializer(board, context={'request': request}).data,
            'posts': serializer.data
        }
        return Response(response_data)

    def perform_create(self, serializer):
        board = get_object_or_404(Board, pk=self.kwargs.get('board_id'))
        self.check_object_permissions(self.request, board)
        serializer.save(author=self.request.user, board=board)

@extend_schema(tags=['게시글'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 상세 조회",
        description='''''게시글의 상세 정보를 조회합니다.\n- **권한 (Board Level)**: 먼저 게시판의 `read_permission`을 확인합니다.\n- **권한 (Post Level)**: 그 다음, 게시글의 `post_type`에 따라 상세 조회 권한이 결정됩니다.\n  - `DEFAULT` (일반): 게시판 읽기 권한이 있으면 누구나 조회 가능\n  - `STAFF_ONLY` (스태프 전용): 스태프만 조회 가능\n  - `JUSTIFICATION_LETTER` (해명글): 작성자 또는 스태프만 조회 가능\n- **조회수 증가**: 이 API를 호출하면 해당 게시글의 조회수가 1 증가합니다.''''', 
        responses={
            200: PostDetailResponseSerializer,
            403: OpenApiResponse(description="게시글을 읽을 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시글입니다."),
        },
    ),
    put=extend_schema(summary="게시글 수정", description="작성자 또는 스태프만 게시글을 수정할 수 있습니다."),
    patch=extend_schema(summary="게시글 부분 수정", description="작성자 또는 스태프만 게시글을 부분 수정할 수 있습니다."),
    delete=extend_schema(summary="게시글 삭제", description="작성자 또는 스태프만 게시글을 삭제할 수 있습니다.")
)
class PostRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Post.objects.all()
    permission_classes = [IsBoardReadable, PostDetailPermission, IsOwnerOrReadOnly]
    lookup_url_kwarg = 'post_id'

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return PostCreateUpdateSerializer
        return PostDetailSerializer  

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.views += 1
        instance.save(update_fields=['views'])
        
        serializer = self.get_serializer(instance, context={'request': request})
        return Response(serializer.data)

@extend_schema(tags=['댓글'])
@extend_schema_view(
    get=extend_schema(summary="댓글 목록 조회"),
    post=extend_schema(
        summary="댓글 생성",
        description="""특정 게시글에 새로운 댓글을 작성합니다.\n- **권한 (Board Level)**: 게시판의 `comment_permission` 설정에 따라 접근이 제어됩니다.\n  - `all`: 인증된 사용자 누구나 작성 가능\n  - `staff`: 스태프만 작성 가능""",
    )
)
class CommentListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsCommentWritable()]
        return [AllowAny()]

    def get_queryset(self):
        post_id = self.kwargs.get('post_id')
        return Comment.objects.filter(post_id=post_id, parent__isnull=True).order_by('created_at')

    def perform_create(self, serializer):
        post = get_object_or_404(Post, pk=self.kwargs.get('post_id'))
        serializer.save(author=self.request.user, post=post)

@extend_schema(tags=['댓글'])
@extend_schema_view(
    put=extend_schema(summary="댓글 수정", description="작성자 또는 스태프만 댓글을 수정할 수 있습니다."),
    patch=extend_schema(summary="댓글 부분 수정", description="작성자 또는 스태프만 댓글을 부분 수정할 수 있습니다."),
    delete=extend_schema(summary="댓글 삭제", description="작성자 또는 스태프만 댓글을 삭제할 수 있습니다.")
)
class CommentUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsOwnerOrReadOnly]
    lookup_url_kwarg = 'comment_id'

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save()

@extend_schema(tags=['첨부파일'])
@extend_schema_view(
    post=extend_schema(
        summary="File 첨부",
        description="서버에 파일을 업로드하고 첨부파일 ID를 반환합니다. 파일 크기는 10MB로 제한되며, 허용된 파일 형식만 업로드할 수 있습니다."
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
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        MAX_FILE_SIZE = 10 * 1024 * 1024
        if file.size > MAX_FILE_SIZE:
            return Response(
                {"error": f"File size exceeds the limit of {MAX_FILE_SIZE // 1024 // 1024} MB."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ALLOWED_MIME_TYPES = [
            'image/jpeg', 'image/png', 'image/gif', 'application/pdf',
            'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'text/plain', 'application/zip', 'application/x-7z-compressed',
            'application/x-hwp', 'application/haansofthwp'
        ]
        if file.content_type not in ALLOWED_MIME_TYPES:
            return Response(
                {"error": f"File type '{file.content_type}' is not allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(filename=self.request.data.get('file').name)


@extend_schema(tags=['게시글'])
@extend_schema_view(
    get=extend_schema(
        summary="전체 게시글 목록 조회",
        description="모든 게시판의 게시글 목록을 조회합니다. 사용자의 권한에 따라 접근 가능한 게시판 및 게시글만 필터링되어 보여집니다.",
    )
)
class AllPostListAPIView(generics.ListAPIView):
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        user = self.request.user
        queryset = Post.objects.visible_for_user(user)
        
        if not (user.is_authenticated and user.is_staff):
            queryset = queryset.filter(board__read_permission='all')
                
        return queryset.order_by('-created_at')


@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="게시판 상세 정보 조회",
        description="특정 게시판의 상세 정보를 조회합니다.",
    )
)
class BoardDetailAPIView(generics.RetrieveAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'board_id'
    permission_classes = [IsBoardReadable]