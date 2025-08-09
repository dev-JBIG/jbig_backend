from django.urls import path
from .views import (
    SignUpView,
    SignInView,
    EmailVerifyView,
    CustomTokenRefreshView,
    ResendVerificationEmailView,
    LogoutView
)

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('signin/', SignInView.as_view(), name='signin'),
    path('verify/', EmailVerifyView.as_view(), name='email-verify'),
    path('resend-verify-email/', ResendVerificationEmailView.as_view(), name='resend-verify-email'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
