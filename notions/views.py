from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from .models import Notion
from .serializers import NotionSerializer, NotionListSerializer

class NotionViewSet(viewsets.ModelViewSet):
    """
    Notion 콘텐츠를 관리하는 ViewSet
    - 관리자만 생성, 수정, 삭제 가능
    - 누구나 목록, 상세 조회 가능
    """
    queryset = Notion.objects.all()

    def get_serializer_class(self):
        if self.action == 'list':
            return NotionListSerializer
        return NotionSerializer

    def get_permissions(self):
        """
        - GET (list, retrieve): 누구나
        - POST, PUT, PATCH, DELETE: 관리자만
        """
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)