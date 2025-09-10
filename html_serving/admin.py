from django.contrib import admin
from django.urls import path
from .models import Notion
from .views import notion_admin_upload_view

@admin.register(Notion)
class NotionAdmin(admin.ModelAdmin):
    list_display = ('title', 'file_path')
    search_fields = ('title', 'file_path')
    change_list_template = 'admin/html_serving/notion/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('upload_zip/', self.admin_site.admin_view(notion_admin_upload_view), name='upload_zip'),
        ]
        return custom_urls + urls
