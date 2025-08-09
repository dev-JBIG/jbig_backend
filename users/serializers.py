from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from rest_framework import serializers
from .models import User

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

        # Send verification email
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        verification_url = reverse('verify-email', kwargs={'uidb64': uid, 'token': token})
        
        # Note: Replace 'yourdomain.com' with your actual domain
        full_verification_url = f"http://localhost:8000{verification_url}"

        subject = '[JBIG] 회원가입 인증 메일'
        message = f'다음 링크를 클릭하여 이메일을 인증하세요: {full_verification_url}'
        send_mail(subject, message, None, [user.email])

        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('email', 'username', 'semester')

class EmailSendSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증 코드를 받을 이메일 주소")

class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증 코드를 받을 이메일 주소")
    verifyCode = serializers.CharField(help_text="이메일로 전송된 인증 코드", required=False)
