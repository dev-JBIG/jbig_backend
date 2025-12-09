import os
import json

from django.http import JsonResponse
from django.conf import settings

from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from .models import CalendarEvent, SiteSettings
from .serializers import CalendarEventSerializer
from .permissions import IsStaffOrReadOnly


def version_info(request):
    """배포된 버전 정보 반환 (commit hash, branch, deploy time)"""
    version_file = os.path.join(settings.BASE_DIR, 'VERSION.json')
    try:
        with open(version_file, 'r') as f:
            data = json.load(f)
            return JsonResponse(data)
    except FileNotFoundError:
        return JsonResponse({'error': 'VERSION.json not found', 'commit': 'unknown'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid VERSION.json'}, status=500)

@extend_schema(
    summary="Quiz URL Management",
    description="Retrieve or update the quiz URL. Only admins can update the URL.",
)
class QuizUrlView(APIView):
    def get_permissions(self):
        if self.request.method == 'PUT':
            return [IsAdminUser()]
        return [IsAuthenticated()]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                "Example Response",
                value={"quiz_url": "https://forms.gle/example123"},
                response_only=True
            )
        ]
    )
    def get(self, request):
        url = SiteSettings.get('quiz_url', '')
        return Response({'quiz_url': url or None})

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {'quiz_url': {'type': 'string', 'format': 'uri'}},
                'required': ['quiz_url']
            }
        },
        responses={200: OpenApiTypes.OBJECT}
    )
    def put(self, request):
        url = request.data.get('quiz_url')
        if not url:
            return Response({'error': 'quiz_url is required'}, status=status.HTTP_400_BAD_REQUEST)
        SiteSettings.set('quiz_url', url)
        return Response({'message': 'Quiz URL updated successfully', 'quiz_url': url})


@extend_schema(
    summary="Site Settings Management",
    description="Retrieve or update site settings. Only admins can update.",
)
class SiteSettingsView(APIView):
    def get_permissions(self):
        if self.request.method in ['PUT', 'PATCH']:
            return [IsAdminUser()]
        return [AllowAny()]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                "Example Response",
                value={
                    "notion_page_id": "abc123",
                    "quiz_url": "https://forms.gle/...",
                    "jbig_description": "'JBIG'(JBNU Big Data & AI Group)은 데이터 사이언스와 딥러닝, 머신러닝을 포함한 AI에 대한 학술 교류를 목표로 2021년 설립된 전북대학교의 학생 학회입니다.",
                    "jbig_president": "박성현",
                    "jbig_president_dept": "전자공학부",
                    "jbig_vice_president": "국환",
                    "jbig_vice_president_dept": "사회학과",
                    "jbig_email": "green031234@naver.com",
                    "jbig_advisor": "최규빈 교수님",
                    "jbig_advisor_dept": "통계학과"
                },
                response_only=True
            )
        ]
    )
    def get(self, request):
        return Response({
            'notion_page_id': SiteSettings.get('notion_page_id', ''),
            'quiz_url': SiteSettings.get('quiz_url', ''),
            'jbig_description': SiteSettings.get('jbig_description', "'JBIG'(JBNU Big Data & AI Group)은 데이터 사이언스와 딥러닝, 머신러닝을 포함한 AI에 대한 학술 교류를 목표로 2021년 설립된 전북대학교의 학생 학회입니다."),
            'jbig_president': SiteSettings.get('jbig_president', '박성현'),
            'jbig_president_dept': SiteSettings.get('jbig_president_dept', '전자공학부'),
            'jbig_vice_president': SiteSettings.get('jbig_vice_president', '국환'),
            'jbig_vice_president_dept': SiteSettings.get('jbig_vice_president_dept', '사회학과'),
            'jbig_email': SiteSettings.get('jbig_email', 'green031234@naver.com'),
            'jbig_advisor': SiteSettings.get('jbig_advisor', '최규빈 교수님'),
            'jbig_advisor_dept': SiteSettings.get('jbig_advisor_dept', '통계학과'),
        })

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'notion_page_id': {'type': 'string'},
                    'quiz_url': {'type': 'string', 'format': 'uri'},
                    'jbig_description': {'type': 'string'},
                    'jbig_president': {'type': 'string'},
                    'jbig_president_dept': {'type': 'string'},
                    'jbig_vice_president': {'type': 'string'},
                    'jbig_vice_president_dept': {'type': 'string'},
                    'jbig_email': {'type': 'string', 'format': 'email'},
                    'jbig_advisor': {'type': 'string'},
                    'jbig_advisor_dept': {'type': 'string'}
                }
            }
        },
        responses={200: OpenApiTypes.OBJECT}
    )
    def put(self, request):
        updated = {}
        fields = [
            'notion_page_id', 'quiz_url', 'jbig_description', 'jbig_president', 'jbig_president_dept',
            'jbig_vice_president', 'jbig_vice_president_dept', 'jbig_email',
            'jbig_advisor', 'jbig_advisor_dept'
        ]
        
        for field in fields:
            if field in request.data:
                SiteSettings.set(field, request.data[field])
                updated[field] = request.data[field]
        
        if not updated:
            return Response({'error': 'No valid fields provided'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': 'Settings updated', **updated})

@extend_schema(tags=['Calendar'])
class CalendarEventViewSet(viewsets.ModelViewSet):
    serializer_class = CalendarEventSerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def get_queryset(self):
        return CalendarEvent.objects.all()
