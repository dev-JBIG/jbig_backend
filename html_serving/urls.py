from django.urls import path
from .views import (
    notion_view, award_view, notion_upload_view, award_upload_view,
    banner_view, notion_admin_upload_view, notion_page_proxy, notion_page_info
)

urlpatterns = [
    path('notion/', notion_view, name='notion'),
    path('notion/page/<str:page_id>/', notion_page_proxy, name='notion-page-proxy'),
    path('notion/info/<str:page_id>/', notion_page_info, name='notion-page-info'),
    path('award/', award_view, name='award'),
    path('notion/upload/', notion_upload_view, name='notion-upload'),
    path('notion/admin_upload/', notion_admin_upload_view, name='notion-admin-upload'),
    path('award/upload/', award_upload_view, name='award-upload'),
    path('banner/', banner_view, name='banner'),
]