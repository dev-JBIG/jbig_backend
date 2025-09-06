from django.urls import path
from .views import (
    SignUpView,
    SignInView,
    EmailVerifyView,
    CustomTokenRefreshView,
    ResendVerificationEmailView,
    LogoutView,
    UserPostListView,
    UserCommentListView,
    PasswordResetRequestView,
    VerifyPasswordCodeView,
    PasswordResetView,
    UserProfileView,
    PasswordChangeView,
)

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('signin/', SignInView.as_view(), name='signin'),
    path('verify/', EmailVerifyView.as_view(), name='email-verify'),
    path('resend-verify-email/', ResendVerificationEmailView.as_view(), name='resend-verify-email'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('<str:user_id>/posts/', UserPostListView.as_view(), name='user-posts'),
    path('<str:user_id>/comments/', UserCommentListView.as_view(), name='user-comments'),
    path('password/reset/request/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password/reset/verify/', VerifyPasswordCodeView.as_view(), name='password-reset-verify'),
    path('password/reset/', PasswordResetView.as_view(), name='password-reset'),
    path('password/change/', PasswordChangeView.as_view(), name='password-change'),
    path('<str:user_id>/', UserProfileView.as_view(), name='user-profile'),
]