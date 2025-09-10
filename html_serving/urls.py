from django.urls import path
from .views import notion_view, award_view, notion_upload_view, award_upload_view, banner_view, notion_admin_upload_view

urlpatterns = [
    path('notion/', notion_view, name='notion'),
    path('award/', award_view, name='award'),
    path('notion/upload/', notion_upload_view, name='notion-upload'),
    path('notion/admin_upload/', notion_admin_upload_view, name='notion-admin-upload'),
    path('award/upload/', award_upload_view, name='award-upload'),
    path('banner/', banner_view, name='banner'),
]