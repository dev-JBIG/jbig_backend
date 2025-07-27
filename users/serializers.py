from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, help_text="사용자 비밀번호")

    class Meta:
        model = User
        fields = ('email', 'username', 'password')
        extra_kwargs = {
            'email': {'help_text': "사용자 이메일 주소"},
            'username': {'help_text': "사용자 이름"}
        }

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            username=validated_data['username'],
            password=validated_data['password']
        )
        return user

class EmailSendSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증 코드를 받을 이메일 주소")

class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="인증 코드를 받을 이메일 주소")
    verifyCode = serializers.CharField(help_text="이메일로 전송된 인증 코드", required=False)
