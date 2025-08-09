from django.urls import path
from .views import (
    SignUpView, SignInView, EmailSendView, EmailVerifyView, CustomTokenRefreshView, VerifyEmailView
)

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('signin/', SignInView.as_view(), name='signin'),
    path('email/send/', EmailSendView.as_view(), name='email-send'),
    path('email/verify/', EmailVerifyView.as_view(), name='email-verify'),
    path('verify-email/<str:uidb64>/<str:token>/', VerifyEmailView.as_view(), name='verify-email'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
]
