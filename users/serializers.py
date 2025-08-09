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
from rest_framework.exceptions import AuthenticationFailed
from .models import User, EmailVerificationCode

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        
        user = self.user
        if not user.is_active:
            raise AuthenticationFailed("User account is not active.", code="user_not_active")
        
        data['username'] = user.username
        data['email'] = user.email
        data['semester'] = user.semester
        return data

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # self.context['request'].user는 토큰 검증 후 인증된 사용자 객체입니다.
        user = self.context['request'].user
        
        # 응답 데이터에 사용자 정보 추가
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
