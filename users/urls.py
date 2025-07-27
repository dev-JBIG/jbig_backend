from django.urls import path
from .views import SignUpView, SignInView, EmailSendView, EmailVerifyView

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('signin/', SignInView.as_view(), name='signin'),
    path('email/send/', EmailSendView.as_view(), name='email-send'),
    path('email/verify/', EmailVerifyView.as_view(), name='email-verify'),
]
