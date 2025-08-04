from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NotionViewSet

router = DefaultRouter()
router.register(r'notions', NotionViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
