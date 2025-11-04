from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from users.views import LogoutView
from .views import QuizUrlView, CalendarEventViewSet

from boards.views import GeneratePresignedURLAPIView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'calendar', CalendarEventViewSet, basename='calendar')

urlpatterns = [
    path('api/', include(router.urls)),
    path('django-admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/', include('boards.urls')),
    path('api/html/', include('html_serving.urls')), # Added this line
    path('api/quiz-url/', QuizUrlView.as_view(), name='quiz_url'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/token/logout/', LogoutView.as_view(), name='logout'),
    path('api/boards/files/generate-upload-url/', GeneratePresignedURLAPIView.as_view(), name='file-generate-upload-url'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
