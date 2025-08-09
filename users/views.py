from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.utils import extend_schema, OpenApiExample
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
from django.conf import settings

from django.contrib.auth import authenticate
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

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
        try:
            # 입력 데이터 검증
            validation_error = self.validate_request_data(request.data)
            if validation_error:
                return validation_error

            # 사용자 인증 시도
            response = super().post(request, *args, **kwargs)
            
            # 로그인 성공 시 사용자 정보 추가
            if response.status_code == 200:
                return self.add_user_info_to_response(response, request.data)
            else:
                # 토큰 생성 실패 시 구체적인 오류 메시지
                return self.handle_authentication_error(response)
                
        except Exception as e:
            return Response({
                "isSuccess": False,
                "errorCode": "LOGIN_UNEXPECTED_ERROR",
                "message": "로그인 처리 중 예상치 못한 오류가 발생했습니다.",
                "detail": str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def validate_request_data(self, data):
        """요청 데이터 검증"""
        email = data.get('email', '').strip()
        password = data.get('password', '')

        # 이메일 필수 확인
        if not email:
            return Response({
                "isSuccess": False,
                "errorCode": "EMAIL_REQUIRED",
                "message": "이메일을 입력해주세요.",
                "field": "email"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 패스워드 필수 확인
        if not password:
            return Response({
                "isSuccess": False,
                "errorCode": "PASSWORD_REQUIRED",
                "message": "비밀번호를 입력해주세요.",
                "field": "password"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 이메일 형식 검증
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return Response({
                "isSuccess": False,
                "errorCode": "INVALID_EMAIL_FORMAT",
                "message": "올바른 이메일 형식이 아닙니다.",
                "field": "email"
            }, status=status.HTTP_400_BAD_REQUEST)

        return None

    def add_user_info_to_response(self, response, request_data):
        """로그인 성공 시 사용자 정보 추가"""
        try:
            user = User.objects.get(email=request_data['email'])
            response.data.update({
                'isSuccess': True,
                'username': user.username,
                'email': user.email,
                'semester': getattr(user, 'semester', None),
                'message': '로그인에 성공했습니다.'
            })
            return response
        except User.DoesNotExist:
            return Response({
                "isSuccess": False,
                "errorCode": "USER_NOT_FOUND_AFTER_AUTH",
                "message": "인증 후 사용자 정보를 찾을 수 없습니다."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def handle_authentication_error(self, response):
        """인증 실패 시 구체적인 오류 처리"""
        # serializer의 오류 내용 분석
        if hasattr(response, 'data') and response.data:
            error_detail = response.data
            
            # non_field_errors가 있는 경우 (일반적인 인증 실패)
            if 'non_field_errors' in error_detail:
                error_messages = error_detail['non_field_errors']
                if any('credentials' in str(msg).lower() for msg in error_messages):
                    return Response({
                        "isSuccess": False,
                        "errorCode": "INVALID_CREDENTIALS",
                        "message": "이메일 또는 비밀번호가 올바르지 않습니다.",
                        "detail": "입력하신 계정 정보를 다시 확인해주세요."
                    }, status=status.HTTP_401_UNAUTHORIZED)
            
            # 개별 필드 오류 처리
            if 'email' in error_detail:
                return Response({
                    "isSuccess": False,
                    "errorCode": "INVALID_EMAIL",
                    "message": "올바르지 않은 이메일입니다.",
                    "field": "email",
                    "detail": error_detail['email']
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if 'password' in error_detail:
                return Response({
                    "isSuccess": False,
                    "errorCode": "INVALID_PASSWORD",
                    "message": "올바르지 않은 비밀번호입니다.",
                    "field": "password",
                    "detail": error_detail['password']
                }, status=status.HTTP_400_BAD_REQUEST)

        # 기본 인증 실패 응답
        return Response({
            "isSuccess": False,
            "errorCode": "AUTHENTICATION_FAILED",
            "message": "로그인에 실패했습니다. 계정 정보를 확인해주세요.",
            "statusCode": response.status_code
        }, status=status.HTTP_401_UNAUTHORIZED)


class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer

    @extend_schema(
        tags=["Authentication"],
        summary="JWT 토큰 재발급",
        description="Refresh 토큰을 사용하여 새로운 Access 토큰을 발급받습니다.",
        examples=[
            OpenApiExample(
                'Successful Response',
                summary='A successful response.',
                description='A successful response.',
                value={
                    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "username": "testuser",
                    "semester": 1,
                    "email": "test@example.com"
                },
                response_only=True,
            ),
        ]
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

        # Check if code is valid (5 minutes expiration)
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
