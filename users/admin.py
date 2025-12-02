from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'semester', 'is_verified', 'can_use_gpu', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('is_verified', 'can_use_gpu', 'is_active', 'is_staff', 'is_superuser', 'semester')
    search_fields = ('username', 'email')

    # first_name, last_name 제거된 fieldsets
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('개인정보', {'fields': ('username', 'semester', 'resume')}),
        ('권한', {'fields': ('is_active', 'is_verified', 'can_use_gpu', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('날짜', {'fields': ('last_login', 'date_joined', 'password_changed_at')}),
    )

    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'username', 'password1', 'password2', 'semester')}),
    )

    ordering = ('-date_joined',)
