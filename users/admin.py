from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin # 기본 UserAdmin 가져오기
from .models import User # User 모델 가져오기

# User 모델을 Django Admin에 등록.
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # 목록 페이지에 표시할 필드
    list_display = ('username', 'email', 'semester', 'is_verified', 'can_use_gpu', 'is_active', 'is_staff', 'date_joined')

    # 필터링 가능한 필드
    list_filter = ('is_verified', 'can_use_gpu', 'is_active', 'is_staff', 'is_superuser', 'semester')

    # 검색 가능한 필드
    search_fields = ('username', 'email')

    # 상세 페이지 필드 그룹화
    fieldsets = BaseUserAdmin.fieldsets + (
        ('추가 정보', {
            'fields': ('semester', 'is_verified', 'can_use_gpu', 'password_changed_at')
        }),
    )

