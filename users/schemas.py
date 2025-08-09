from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
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
            examples=[
                OpenApiExample(
                    "Success",
                    value={"isSuccess": True},
                    response_only=True,
                )
            ]
        ),
        400: OpenApiResponse(description="잘못된 요청 데이터 (유효성 검사 실패)"),
    },
    tags=["Authentication"]
)

# 로그인 스키마
signin_schema = extend_schema(
    summary="로그인",
    description="사용자 인증을 통해 JWT 토큰을 발급받습니다.",
    request=UserSerializer,
    examples=[
        OpenApiExample(
            "로그인 요청 예시",
            description="일반적인 로그인 요청",
            value={
                "email": "user@example.com",
                "password": "password123"
            },
            request_only=True
        )
    ],
    responses={
        200: OpenApiResponse(
            description="로그인 성공",
            examples=[
                OpenApiExample(
                    "Success",
                    value={
                        "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                        "username": "사용자이름"
                    },
                    response_only=True
                )
            ]
        ),
        401: OpenApiResponse(
            description="잘못된 인증 정보 또는 비활성 사용자",
            examples=[
                OpenApiExample(
                    "Inactive User Error",
                    value={
                        "detail": "User account is not active."
                    },
                    response_only=True
                ),
                OpenApiExample(
                    "Invalid Credentials Error",
                    value={
                        "detail": "No active account found with the given credentials"
                    },
                    response_only=True
                )
            ]
        ),
        400: OpenApiResponse(description="잘못된 요청 데이터")
    },
    tags=["Authentication"]
)

# 이메일 인증 스키마
email_verify_schema = extend_schema(
    summary="이메일 인증 토큰 확인",
    description="전송된 인증 토큰을 확인하여 이메일을 인증합니다. 성공 시 is_verified가 True로 설정됩니다. is_active는 관리자가 수동으로 활성화합니다.",
    request=EmailVerificationSerializer,
    responses={
        200: OpenApiResponse(
            description="인증 성공",
            examples=[
                OpenApiExample(
                    "Success",
                    value={"success verify"},
                    response_only=True
                )
            ]
        ),
        400: OpenApiResponse(
            description="잘못된 인증 번호 또는 요청 데이터",
            examples=[
                OpenApiExample(
                    "Error",
                    value={
                        "error": "Invalid verification verifyCode."
                    },
                    response_only=True
                )
            ]
        ),
        404: OpenApiResponse(
            description="사용자를 찾을 수 없음",
            examples=[
                OpenApiExample(
                    "User Not Found",
                    value={
                        "error": "User not found"
                    },
                    response_only=True
                )
            ]
        )
    },
    tags=["Authentication"]
)

# 이메일 인증코드 전송 스키마
email_send_schema = extend_schema(
    summary="이메일 인증코드 전송",
    description="회원가입을 위해 이메일로 인증코드를 전송합니다.",
    request=EmailSendSerializer,
    responses={
        200: OpenApiResponse(
            description="인증코드 전송 성공",
            examples=[
                OpenApiExample(
                    "Success",
                    value={"duplicateMail": False},
                    response_only=True
                )
            ]
        ),
        400: OpenApiResponse(description="잘못된 요청 데이터"),
    },
    tags=["Authentication"]
)
