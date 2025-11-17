from django.http import HttpResponse, Http404
from django.conf import settings
import os
from pathlib import Path
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAdminUser, AllowAny
from drf_spectacular.utils import extend_schema, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from .models import CalendarEvent
from .serializers import CalendarEventSerializer
from .permissions import IsStaffOrReadOnly


QUIZ_URL_FILE_PATH = os.path.join(settings.MEDIA_ROOT, 'quiz_url.txt')

def serve_html(request, file_path):
    """
    Reads an HTML file from the media directory and returns it as an HttpResponse.
    """
    # Construct the full path to the file
    full_path = os.path.join(settings.MEDIA_ROOT, file_path)

    # Check if the file exists and is a file
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise Http404("File not found")

    # Read the file content
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except IOError:
        raise Http404("Error reading file")

    return HttpResponse(content, content_type='text/html; charset=utf-8')

@extend_schema(
    summary="Quiz URL Management",
    description="Retrieve or update the quiz URL. Only admins can update the URL.",
)
class QuizUrlView(APIView):
    def get_permissions(self):
        if self.request.method == 'PUT':
            return [IsAdminUser()]
        return [AllowAny()]

    @extend_schema(
        responses={
            200: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Example Response",
                value={"quiz_url": "https://forms.gle/example123"},
                response_only=True
            )
        ]
    )
    def get(self, request):
        """Retrieve the current quiz URL."""
        try:
            if os.path.exists(QUIZ_URL_FILE_PATH):
                with open(QUIZ_URL_FILE_PATH, 'r') as f:
                    url = f.read().strip()
                return Response({'quiz_url': url})
            return Response({'quiz_url': None}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'quiz_url': {'type': 'string', 'format': 'uri'}
                },
                'required': ['quiz_url']
            }
        },
        examples=[
            OpenApiExample(
                "Example Request",
                value={"quiz_url": "https://forms.gle/new_quiz_url"},
                request_only=True
            )
        ],
        responses={
            200: OpenApiTypes.OBJECT,
        }
    )
    def put(self, request):
        """Update the quiz URL. (Admin only)"""
        url = request.data.get('quiz_url')
        if not url:
            return Response({'error': 'quiz_url is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            os.makedirs(os.path.dirname(QUIZ_URL_FILE_PATH), exist_ok=True)
            with open(QUIZ_URL_FILE_PATH, 'w') as f:
                f.write(url)
            return Response({'message': 'Quiz URL updated successfully', 'quiz_url': url})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@extend_schema(tags=['Calendar'])
class CalendarEventViewSet(viewsets.ModelViewSet):
    serializer_class = CalendarEventSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def get_queryset(self):
        return CalendarEvent.objects.all()


class ReleaseInfoView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Returns metadata about the currently running release so deploy status can be verified.
        """
        base_dir = Path(settings.BASE_DIR).resolve()

        data = {
            "release_path": str(base_dir),
            "release_name": base_dir.name,
        }
        return Response(data)
