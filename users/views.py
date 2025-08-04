from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import UserSerializer, EmailVerificationSerializer, EmailSendSerializer
from .models import User

# schemas.py에서 스키마들 import
from .schemas import (
    signup_schema, signin_schema, email_send_schema, email_verify_schema
)
from rest_framework.parsers import JSONParser, FormParser


class SignUpView(generics.CreateAPIView):
    parser_classes = [JSONParser, FormParser]
    queryset = User.objects.all()
    serializer_class = UserSerializer

    @signup_schema
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        
        return Response({
            "isSuccess": True,
            "created_user": serializer.data
        }, status=status.HTTP_201_CREATED, headers=headers)


class SignInView(TokenObtainPairView):
    parser_classes = [JSONParser, FormParser]
    
    @signin_schema
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            user = User.objects.get(email=request.data['email'])
            response.data['username'] = user.username
            response.data['email'] = user.email
            response.data['semeseter'] = user.semester
        return response


class EmailSendView(APIView):
    serializer_class = EmailSendSerializer
    
    @email_send_schema
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check for duplicate email
        if User.objects.filter(email=email).exists():
            return Response({"duplicateMail": True})

        # Mock sending email
        print(f"Sending verification code to {email}")
        return Response({"duplicateMail": False})


class EmailVerifyView(APIView):
    serializer_class = EmailVerificationSerializer
    
    @email_verify_schema
    def post(self, request, *args, **kwargs):
        serializer = EmailVerificationSerializer(data=request.data)
        if serializer.is_valid():
            # Mock verification
            return Response({"isVerified": True})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)