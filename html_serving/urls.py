from django.urls import path
from .views import notion_view, award_view, banner_view

# 레거시 엔드포인트 - deprecated 응답 반환
urlpatterns = [
    path('notion/', notion_view, name='notion'),
    path('award/', award_view, name='award'),
    path('banner/', banner_view, name='banner'),
]
