from drf_spectacular.utils import extend_schema, OpenApiResponse
from drf_spectacular.openapi import OpenApiTypes
from .serializers import UserSerializer, EmailVerificationSerializer, EmailSendSerializer

# 회원가입 스키마
signup_schema = extend_schema(
    summary="회원가입",
    description="새로운 사용자 계정을 생성합니다.",
    request=UserSerializer,
    responses={
        201: OpenApiResponse(
            description="회원가입 성공",
            examples={
                "application/json": {
                    "isSuccess": True
                }
            }
        ),
        400: OpenApiResponse(description="잘못된 요청 데이터 (유효성 검사 실패)"),
    },
    tags=["Auth"]
)

# 로그인 스키마
signin_schema = extend_schema(
    summary="로그인",
    description="사용자 인증을 통해 JWT 토큰을 발급받습니다.",
    request={
        'type': 'object',
        'properties': {
            'email': {
                'type': 'string',
                'format': 'email',
                'description': '사용자 이메일',
                'example': 'user@example.com'
            },
            'password': {
                'type': 'string',
                'description': '사용자 비밀번호',
                'example': 'password123'
            }
        },
        'required': ['email', 'password']
    },
    responses={
        200: OpenApiResponse(
            description="로그인 성공",
            examples={
                "application/json": {
                    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                    "username": "사용자이름"
                }
            }
        ),
        401: OpenApiResponse(description="잘못된 인증 정보"),
        400: OpenApiResponse(description="잘못된 요청 데이터")
    },
    tags=["Auth"]
)

# 이메일 전송 스키마
email_send_schema = extend_schema(
    summary="이메일 인증코드 전송",
    description="회원가입 시 이메일 중복 확인 및 인증코드 전송을 위한 API입니다.",
    request=EmailSendSerializer,
    responses={
        200: OpenApiResponse(
            description="이메일 전송 결과",
            examples={
                "application/json": {
                    "duplicateMail": False,
                    "message": "인증코드가 전송되었습니다."
                }
            }
        ),
        400: OpenApiResponse(
            description="이메일 중복 또는 잘못된 요청",
            examples={
                "application/json": {
                    "duplicateMail": True
                }
            }
        )
    },
    tags=["Auth"]
)

# 이메일 인증 스키마
email_verify_schema = extend_schema(
    summary="이메일 인증코드 확인",
    description="전송된 인증코드를 확인하여 이메일을 인증합니다.",
    request=EmailVerificationSerializer,
    responses={
        200: OpenApiResponse(
            description="인증 성공",
            examples={
                "application/json": {
                    "isVerified": True
                }
            }
        ),
        400: OpenApiResponse(
            description="잘못된 인증코드 또는 요청 데이터",
            examples={
                "application/json": {
                    "isVerified": False,
                    "error": "Invalid verification code"
                }
            }
        )
    },
    tags=["Auth"]
)