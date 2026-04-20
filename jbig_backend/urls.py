import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
)
from users.views import LogoutView
from .views import QuizUrlView, CalendarEventViewSet, version_info, SiteSettingsView, PopupViewSet, NotionPageView
from .local_upload import LocalFileUploadView

from boards.views import GeneratePresignedURLAPIView, DeleteFileAPIView, ConfirmUploadAPIView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'calendar', CalendarEventViewSet, basename='calendar')
router.register(r'popups', PopupViewSet, basename='popup')

urlpatterns = [
    path('api/', include(router.urls)),
    path('django-admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/', include('boards.urls')),
    path('api/', include('recruitments.urls')),
    path('api/quiz-url/', QuizUrlView.as_view(), name='quiz_url'),
    path('api/settings/', SiteSettingsView.as_view(), name='site_settings'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/logout/', LogoutView.as_view(), name='logout'),
    path('api/boards/files/generate-upload-url/', GeneratePresignedURLAPIView.as_view(), name='file-generate-upload-url'),
    path('api/boards/files/delete/', DeleteFileAPIView.as_view(), name='file-delete'),
    path('api/boards/files/confirm-upload/', ConfirmUploadAPIView.as_view(), name='file-confirm-upload'),
    path('api/notion/<str:page_id>/', NotionPageView.as_view(), name='notion-page'),
    path('api/version/', version_info, name='version-info'),
]

# OpenAPI 스키마 및 Swagger UI는 개발/로컬 환경에서만 노출한다.
# 프로덕션 공개는 공격자에게 엔드포인트 매핑을 그대로 제공하는 꼴이라 기본 차단.
if settings.DEBUG or os.getenv('EXPOSE_API_DOCS') == '1':
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    ]

# 로컬 개발: 파일 업로드 엔드포인트 + media 파일 서빙
if settings.USE_LOCAL_STORAGE:
    urlpatterns += [
        path('api/local-upload/<path:file_key>', LocalFileUploadView.as_view(), name='local-file-upload'),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)