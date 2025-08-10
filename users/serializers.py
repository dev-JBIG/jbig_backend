import random
import string
from django.core.mail import send_mail
from django.utils import timezone # Import timezone
from django.contrib.auth.hashers import make_password, check_password # Import hashing utilities
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer, TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed
from .models import User, EmailVerificationCode

from django.contrib.auth import get_user_model

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        User = get_user_model()

        # 1. 이메일 존재 여부 확인 (대소문자 무시)
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise AuthenticationFailed({
                "isSuccess": False,
                "errorCode": "USER_NOT_FOUND",
                "message": "존재하지 않는 이메일입니다."
            }, code='authentication')

        # 2. 비밀번호 확인
        if not user.check_password(password):
            raise AuthenticationFailed({
                "isSuccess": False,
                "errorCode": "INVALID_PASSWORD",
                "message": "비밀번호가 올바르지 않습니다."
            }, code='authentication')

        # 3. 이메일 인증 여부 확인
        if not user.is_verified:
            raise AuthenticationFailed({
                "isSuccess": False,
                "errorCode": "ACCOUNT_NOT_VERIFIED",
                "message": "이메일 인증이 완료되지 않았습니다. 이메일을 확인해주세요."
            }, code='authentication')

        # 4. 계정 활성 상태 확인
        if not user.is_active:
            raise AuthenticationFailed({
                "isSuccess": False,
                "errorCode": "ACCOUNT_INACTIVE",
                "message": "계정이 비활성화 상태입니다. 관리자에게 문의해주세요."
            }, code='authentication')

        # 모든 검증을 통과한 후, 수동으로 토큰 생성
        refresh = RefreshToken.for_user(user)

        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

        # 응답 데이터에 사용자 정보 추가
        data['isSuccess'] = True
        data['message'] = '로그인에 성공했습니다.'
        data['username'] = user.username
        data['email'] = user.email
        data['semester'] = user.semester
        data['is_staff'] = user.is_staff
        
        return data

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        refresh = RefreshToken(attrs['refresh'])
        user_id = refresh.get('user_id')

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise AuthenticationFailed('User not found', code='user_not_found')

        data['username'] = user.username
        data['semester'] = user.semester
        data['email'] = user.email

        return data



class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, help_text="사용자 비밀번호")
    semester = serializers.IntegerField(help_text="학기 정보")

    class Meta:
        model = User
        fields = ('email', 'username', 'password', 'semester')
        extra_kwargs = {
            'email': {'help_text': "사용자 이메일 주소"},
            'username': {'help_text': "사용자 이름"}
        }

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            username=validated_data['username'],
            password=validated_data['password'],
            semester=validated_data['semester']
        )

        # 6자리 인증 코드 생성
        code = ''.join(random.choices(string.digits, k=6))
        EmailVerificationCode.objects.create(user=user, code=make_password(code))

        # 인증 코드 이메일 발송
        subject = '[JBIG] 회원가입 인증 코드'
        message = f'회원가입을 완료하려면 다음 인증 코드를 입력하세요: {code}'
        send_mail(subject, message, None, [user.email])

        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('email', 'username', 'semester')

class EmailSendSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증 코드를 받을 이메일 주소")

class EmailResendSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증 코드를 재전송할 이메일 주소")

class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증할 이메일 주소")
    verifyCode = serializers.CharField(help_text="이메일로 전송된 6자리 인증 코드")
