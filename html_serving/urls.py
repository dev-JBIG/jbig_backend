from django.urls import path
from .views import notion_view, banner_view

# 레거시 엔드포인트 - deprecated 응답 반환
urlpatterns = [
    path('notion/', notion_view, name='notion'),
    path('banner/', banner_view, name='banner'),
]
