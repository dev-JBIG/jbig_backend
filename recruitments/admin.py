from django.contrib import admin
from .models import Recruitment, Application


@admin.register(Recruitment)
class RecruitmentAdmin(admin.ModelAdmin):
    list_display = ('post', 'recruitment_type', 'status', 'max_members', 'accepted_count', 'deadline')
    list_filter = ('status', 'recruitment_type')
    search_fields = ('post__title',)
    raw_id_fields = ('post',)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('applicant', 'recruitment', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('applicant__username', 'recruitment__post__title')
    raw_id_fields = ('recruitment', 'applicant')
