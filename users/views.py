from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.utils import extend_schema
from .serializers import (
    UserCreateSerializer,
    EmailVerificationSerializer,
    EmailResendSerializer,
    CustomTokenRefreshSerializer,
    CustomTokenObtainPairSerializer,
)
from .models import User, EmailVerificationCode
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib.auth.tokens import default_token_generator
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
import random
import string
from django.core.mail import send_mail

# schemas.py에서 스키마들 import
from .schemas import (
    signup_schema, signin_schema, email_send_schema, email_verify_schema
)
from rest_framework.parsers import JSONParser, FormParser


class SignUpView(generics.CreateAPIView):
    parser_classes = [JSONParser, FormParser]
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer

    @signup_schema
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        semester = request.data.get('semester')
        if semester is not None:
            try:
                semester_int = int(semester)
                if semester_int > 100:
                    return Response({
                        "isSuccess": False,
                        "message": "학기는 100 이하여야 합니다."
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError):
                return Response({
                    "isSuccess": False,
                    "message": "학기는 유효한 숫자여야 합니다."
                }, status=status.HTTP_400_BAD_REQUEST)
                
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        
        return Response({
            "isSuccess": True,
            "message": "회원가입에 성공하였습니다. 인증번호를 확인해주세요."
        }, status=status.HTTP_201_CREATED, headers=headers)


class SignInView(TokenObtainPairView):
    parser_classes = [JSONParser, FormParser]
    serializer_class = CustomTokenObtainPairSerializer
    
    @signin_schema
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer

    @extend_schema(
        tags=["Authentication"],
        summary="JWT 토큰 재발급",
        description="Refresh 토큰을 사용하여 새로운 Access 토큰을 발급받습니다.",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class EmailVerifyView(APIView):
    serializer_class = EmailVerificationSerializer
    
    @email_verify_schema
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        verifyCode = serializer.validated_data['verifyCode']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "User not found"},
                            status=status.HTTP_404_NOT_FOUND)

        if user.is_verified:
            return Response({"message": "This account is already verified."},
                            status=status.HTTP_200_OK)

        try:
            verification_code_obj = EmailVerificationCode.objects.get(user=user)
        except EmailVerificationCode.DoesNotExist:
            return Response({"error": "No verification verifyCode found for this user. Please request a new one."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Check if code is valid (10 minutes expiration)
        if (timezone.now() - verification_code_obj.created_at).total_seconds() > 300:
            return Response({"error": "Verification code has expired."},
                            status=status.HTTP_400_BAD_REQUEST)

        if not check_password(verifyCode, verification_code_obj.code):
            return Response({"error": "Invalid verification code."},
                            status=status.HTTP_400_BAD_REQUEST)
        
        user.is_verified = True
        user.is_active = True
        user.save()
        verification_code_obj.delete()
        return Response({"message": "Email verified successfully."}, status=status.HTTP_200_OK)


class ResendVerificationEmailView(APIView):
    serializer_class = EmailResendSerializer

    @extend_schema(
        tags=["Authentication"],
        summary="Resend Verification Email",
        description="Resends the verification email with a new code.",
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if user.is_verified:
            return Response({"message": "This account is already verified."}, status=status.HTTP_400_BAD_REQUEST)

        # Generate and send new code
        code = ''.join(random.choices(string.digits, k=6))
        hashed_code = make_password(code)

        EmailVerificationCode.objects.update_or_create(
            user=user,
            defaults={'code': hashed_code, 'created_at': timezone.now()}
        )

        subject = '[JBIG] Your New Verification Code'
        message = f'Your new verification code is: {code}'
        send_mail(subject, message, None, [user.email])

        return Response({"message": "A new verification email has been sent."}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Authentication"],
        summary="Logout",
        description="Logs out the user by blacklisting their refresh token.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "string",
                        "description": "The refresh token to be blacklisted."
                    }
                },
                "required": ["refresh"]
            }
        },
        responses={
            205: {"description": "Reset Content - successful logout"},
            400: {"description": "Bad Request - token is invalid or missing"}
        }
    )
    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response(status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response(status=status.HTTP_400_BAD_REQUEST)