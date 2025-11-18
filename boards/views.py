from rest_framework import generics, status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample, OpenApiParameter
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, Q, Value, CharField
from django.db.models.functions import Replace
from django.contrib.postgres.fields import Func
from datetime import datetime

from rest_framework.views import APIView # APIView 추가
from rest_framework.response import Response # Response 추가
from rest_framework import status # status 추가
from rest_framework.permissions import IsAuthenticated # IsAuthenticated 추가


## NCP 연동 위해 새로 추가 ##
import boto3
import uuid
import os
from django.conf import settings
from botocore.client import Config
from botocore.exceptions import ClientError
import logging
logger = logging.getLogger(__name__)




from .models import Board, Post, Comment, Category, Attachment
from .serializers import (
    BoardSerializer, PostListSerializer, PostDetailSerializer, PostCreateUpdateSerializer,
    CommentSerializer, AttachmentSerializer,
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
    tags=['게시판'],
    summary="게시글 좋아요/취소",
    description="특정 게시글에 좋아요를 추가하거나 취소합니다. 이미 좋아요를 누른 상태에서 요청하면 좋아요가 취소됩니다.",
    responses={
        200: {
            'description': '좋아요 상태 변경 성공',
            'examples': {
                '좋아요 추가': {
                    'value': {'likes_count': 28, 'is_liked': True}
                },
                '좋아요 취소': {
                    'value': {'likes_count': 27, 'is_liked': False}
                }
            }
        }
    }
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


class RegexpReplace(Func):
    function = 'REGEXP_REPLACE'
    template = "%(function)s(%(expressions)s, '%(pattern)s', '%(replacement)s', 'g')"

    def __init__(self, expression, pattern, replacement='', **extra):
        super().__init__(
            expression,
            pattern=pattern,
            replacement=replacement,
            output_field=CharField(),
            **extra
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

        # URL/링크를 제거하는 정규식 패턴
        url_pattern = r'!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)|https?://[^\s]+|www\.[^\s]+'
        
        # content_md에서 URL 제거 후 검색
        queryset = queryset.annotate(
            clean_content=RegexpReplace('content_md', url_pattern, '')
        )

        # 부분 검색되게 수정
        search_filter = (
            Q(title__icontains=query) |
            Q(clean_content__icontains=query) |
            Q(author__username__icontains=query)
        )

        queryset = queryset.filter(search_filter).distinct().order_by('-created_at')
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


@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 목록 조회",
        description="""특정 게시판의 정보 및 게시글 목록을 조회합니다.\n- **게시판 접근 권한**: 게시판의 `read_permission` 설정에 따라 접근이 제어됩니다.\n- **게시글 필터링**: 사용자의 권한(스태프, 인증 여부)에 따라 조회되는 게시글이 자동으로 필터링됩니다. (예: 스태프 전용 글, 본인 작성 해명글 등) """,
        responses={
            200: OpenApiResponse(
                response=PostListResponseSerializer,
                examples=[
                    OpenApiExample(
                        'Success',
                        summary='게시글 목록 조회 성공',
                        value={
                            "board": {
                                "id": 1,
                                "name": "자유게시판",
                                "category": {"id": 1, "name": "커뮤니티"},
                                "read_permission": True,
                                "post_permission": True,
                                "comment_permission": True
                            },
                            "count": 1,
                            "next": None,
                            "previous": None,
                            "results": [
                                {
                                    "id": 101,
                                    "board_post_id": 1,
                                    "title": "첫 번째 게시글입니다.",
                                    "user_id": "testuser",
                                    "author": "테스트유저",
                                    "author_semester": 1,
                                    "created_at": "2025-09-17T12:30:00Z",
                                    "views": 150,
                                    "likes_count": 10,
                                    "attachments": [
                                        {"id": 1, "file": "/media/attachments/file1.pdf", "filename": "file1.pdf"}
                                    ]
                                }
                            ]
                        }
                    )
                ]
            ),
            403: OpenApiResponse(description="게시판에 대한 읽기 권한이 없습니다."),
            404: OpenApiResponse(description="존재하지 않는 게시판입니다."),
        },
    ),
    post=extend_schema(
        summary="게시글 생성",
        description="""특정 게시판에 새로운 게시글을 작성합니다.\n- **권한 (Board Level)**: 게시판의 `post_permission` 설정에 따라 접근이 제어됩니다.\n  - `all`: 인증된 사용자 누구나 작성 가능\n  - `staff`: 스태프만 작성 가능""",
        request=PostCreateUpdateSerializer,
        examples=[
            OpenApiExample(
                '게시글 생성 요청',
                summary='새로운 게시글을 작성하는 예시입니다.',
                value={
                    "title": "새로운 게시글 제목",
                    "content_md": "# 제목\n\n여기에 게시글 내용이 마크다운 형식으로 들어갑니다.\n\n- 목록1\n- 목록2",
                    "attachment_paths": [
                        {"url": "http://example.com/media/attachments/file1.pdf", "name": "file1.pdf"},
                        {"url": "http://example.com/media/attachments/file2.jpg", "name": "file2.jpg"}
                    ],
                    "post_type": 1
                }
            )
        ],
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
        # self.check_object_permissions(self.request, obj) # This line causes recursion
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
                'results': paginated_response.data['results']
            }
            return Response(response_data)

        serializer = self.get_serializer(queryset, many=True)
        response_data = {
            'board': BoardSerializer(board, context={'request': request}).data,
            'results': serializer.data
        }
        return Response(response_data)

    def perform_create(self, serializer):
        board = get_object_or_404(Board, pk=self.kwargs.get('board_id'))
        self.check_object_permissions(self.request, board)
        
        post_type = Post.PostType.DEFAULT # Default to DEFAULT
        if board.board_type == Board.BoardType.JUSTIFICATION_LETTER:
            post_type = Post.PostType.JUSTIFICATION_LETTER
        
        serializer.save(author=self.request.user, board=board, post_type=post_type)

@extend_schema(tags=['게시판'])
@extend_schema_view(
    get=extend_schema(
        summary="게시글 상세 조회",
        description=(
            "게시글의 상세 정보를 조회합니다.\n"
            "- 권한 (Board Level): 먼저 게시판의 `read_permission`을 확인합니다.\n"
            "- 권한 (Post Level): 게시글의 `post_type`에 따라 상세 조회 권한이 결정됩니다.\n"
            "  - DEFAULT(일반): 게시판 읽기 권한이 있으면 누구나 조회 가능\n"
            "  - STAFF_ONLY(스태프 전용): 스태프만 조회 가능\n"
            "  - JUSTIFICATION_LETTER(해명글): 작성자 또는 스태프만 조회 가능\n"
            "- 조회수 증가: 이 API를 호출하면 해당 게시글의 조회수가 1 증가합니다."
        ),
        responses={
            200: PostDetailSerializer,
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
    permission_classes = [IsBoardReadable, PostDetailPermission]
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

@extend_schema(
    tags=['파일'],
    summary="파일 첨부",
    description="서버에 파일을 업로드하고 첨부파일 ID를 반환합니다. 파일 크기는 10MB로 제한되며, 허용된 파일 형식만 업로드할 수 있습니다.",
    request={
        'multipart/form-data': {
            'type': 'object',
            'properties': {
                'file': {
                    'type': 'string',
                    'format': 'binary'
                }
            }
        }
    },
    responses={
        201: OpenApiResponse(
            response=AttachmentSerializer,
            examples=[
                OpenApiExample(
                    'Success',
                    summary='파일 업로드 성공',
                    value={
                        "id": 123,
                        "file": "/media/attachments/example.jpg",
                        "filename": "example.jpg"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="파일이 제공되지 않았거나, 파일 크기/형식이 올바르지 않습니다.")
    }
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
            'application/x-hwp', 'application/haansofthwp',
            'video/mp4', 'video/quicktime'
        ]
        if file.content_type not in ALLOWED_MIME_TYPES:
            return Response(
                {"error": f"File type '{file.content_type}' is not allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(filename=self.request.data.get('file').name)


@extend_schema(tags=['게시판'])
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

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})



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



# 업로드 URL 발급해주는 GeneratePresignedURlAPIView 클래스

@extend_schema(
    tags=['파일'], # API 문서에서 '파일' 태그로 분류
    summary="파일 업로드용 Presigned URL 생성",
    description="NCP Object Storage에 파일을 직접 업로드할 수 있는 10분 만료 Presigned URL을 발급받습니다.",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'filename': {'type': 'string', 'example': 'example.png'}
            },
            'required': ['filename']
        }
    },
    responses={
        200: OpenApiResponse(
            description="URL 발급 성공",
            examples=[
                OpenApiExample(
                    'Success',
                    value={
                        "upload_url": "https://kr.object.ncloudstorage.com/jbig/uploads/2025/10/28/12/a1b2c3d4-....png?AWSAccessKeyId=...",
                        "file_key": "uploads/2025/10/28/12/a1b2c3d4-....png"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="파일 이름이 제공되지 않았습니다."),
        500: OpenApiResponse(description="URL 생성에 실패했습니다."),
    }
)
class GeneratePresignedURLAPIView(APIView):
    """
    파일 업로드를 위한 Presigned URL을 생성하는 API
    """
    permission_classes = [IsAuthenticated] # 로그인한 사용자만 이 API를 호출할 수 있음

    def post(self, request, *args, **kwargs):
        filename = request.data.get('filename')
        if not filename:
            return Response({"error": "No filename provided."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user

        # 1. 파일 확장자 추출
        try:
            extension = os.path.splitext(filename)[1].lstrip('.')
            if not extension:
                 # 확장자가 없는 경우 기본값 (혹은 에러 처리)
                extension = 'bin' 
        except Exception:
            extension = 'bin'

        # 2. 서버에서 고유한 파일 경로(Key) 생성
        # uploads/년/월/일/유저ID/고유ID.확장자
        # 예: "uploads/2025/10/28/12/a1b2c3d4-e5f6-4a5b-8c7d-9e0f1a2b3c4d.png"
        file_key = os.path.join(
            "uploads",
            f"{datetime.now():%Y/%m/%d}",
            str(user.id),
            f"{uuid.uuid4()}.{extension}"
        )

        # 3. boto3 클라이언트 생성
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.NCP_ENDPOINT_URL,
                aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
                aws_secret_access_key=settings.NCP_SECRET_KEY,
                config=Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'},
                    region_name=settings.NCP_REGION_NAME
                )
            )
        except Exception as e:
            logger.error(f"S3 클라이언트 생성 실패: {e}")
            return Response({"error": "S3 client creation failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 4. Presigned URL (업로드용) 생성
        try:
            # URL 만료 시간: 600초 (10분)
            upload_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.NCP_BUCKET_NAME,
                    'Key': file_key,
                    # 'ContentType': 'image/png' # 필요시 파일 타입 지정
                },
                ExpiresIn=600 
            )

            # [추가] 다운로드용 URL도 미리 생성 (1시간 만료)
            download_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.NCP_BUCKET_NAME,
                    'Key': file_key,
                }
               # ExpiresIn=3600
            )

            # React에게 업로드할 URL과 DB에 저장할 Key를 함께 전달
            return Response({
                "upload_url": upload_url,
                "file_key": file_key,
                "download_url": download_url
            }, status=status.HTTP_200_OK)

        except ClientError as e:
            logger.error(f"Presigned URL 생성 실패: {e}")
            return Response({"error": "Failed to generate presigned URL."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"알 수 없는 에러: {e}")
            return Response({"error": "An unknown error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
