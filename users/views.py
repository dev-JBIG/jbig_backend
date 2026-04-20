
from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from rest_framework import generics, status
from rest_framework.parsers import JSONParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter
from .serializers import (
    UserCreateSerializer,
    EmailVerificationSerializer,
    EmailResendSerializer,
    CustomTokenObtainPairSerializer,
    UserProfileSerializer,
    PasswordChangeSerializer,
    PasswordResetRequestSerializer,
    VerifyPasswordCodeSerializer,
    PasswordResetSerializer,
    PublicProfileSerializer,
    ResumeUpdateSerializer,
    ProfileBlocksUpdateSerializer
)
from .models import User, EmailVerificationCode
from .password_reset_token import (
    RESET_TOKEN_TTL_SECONDS,
    ResetTokenError,
    consume_reset_token,
    issue_reset_token,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed

MAX_VERIFICATION_ATTEMPTS = 5
import random
import string
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
import pytz

from rest_framework_simplejwt.exceptions import TokenError
from boards.serializers import PostListSerializer, CommentSerializer
from boards.models import Post, Comment




@extend_schema(
    tags=["사용자"],
    summary="특정 사용자가 작성한 게시글 목록 조회",
    description="""특정 사용자의 username을 이용하여 해당 사용자가 작성한 모든 게시글의 목록을 조회합니다.
    
- 로그인한 사용자: 실명 작성글과 익명 작성글 모두 조회 가능
- 비로그인 사용자(비회원): 실명 작성글만 조회 가능 (익명 작성글은 제외됨)
- 본인의 프로필: 익명 작성글도 모두 확인 가능""",
    parameters=[
        OpenApiParameter(
            name='user_id',
            type=str,
            location=OpenApiParameter.PATH,
            description="사용자 username"
        )
    ]
)
class UserPostListView(generics.ListAPIView):
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        username = (self.kwargs['user_id'] or '').strip().lower()
        target_user = get_object_or_404(User, email__iexact=f'{username}@jbnu.ac.kr')
        request_user = self.request.user

        queryset = Post.objects.filter(author=target_user)
        
        # 로그인하지 않은 사용자는 익명 글을 볼 수 없음
        if not request_user.is_authenticated:
            queryset = queryset.filter(is_anonymous=False)
        
        return queryset.order_by('-created_at')


@extend_schema(
    tags=["사용자"],
    summary="특정 사용자가 작성한 댓글 목록 조회",
    description="""특정 사용자의 ID를 이용하여 해당 사용자가 작성한 모든 댓글의 목록을 조회합니다.
    
- 로그인한 사용자: 실명 댓글과 익명 댓글 모두 조회 가능
- 비로그인 사용자(비회원): 실명 댓글만 조회 가능 (익명 댓글은 제외됨)
- 본인의 프로필: 익명 댓글도 모두 확인 가능""",
    parameters=[
        OpenApiParameter(
            name='user_id',
            type=str,
            location=OpenApiParameter.PATH,
            description="사용자 ID (이메일의 '@' 앞 부분)"
        )
    ]
)
class UserCommentListView(generics.ListAPIView):
    serializer_class = CommentSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        user_id = (self.kwargs['user_id'] or '').strip().lower()
        target_user = get_object_or_404(User, email__iexact=f'{user_id}@jbnu.ac.kr')
        request_user = self.request.user

        queryset = Comment.objects.filter(author=target_user)
        
        # 로그인하지 않은 사용자는 익명 댓글을 볼 수 없음
        if not request_user.is_authenticated:
            queryset = queryset.filter(is_anonymous=False)
        
        return queryset.order_by('-created_at')

@extend_schema(
    tags=["사용자"],
    summary="회원가입",
    description="새로운 사용자를 등록합니다. 성공 시 인증 이메일이 발송됩니다.",
    request=UserCreateSerializer,
    responses={
        201: {
            'description': '회원가입 성공',
            'examples': {
                'Success': {
                    'value': {
                        "isSuccess": True,
                        "message": "회원가입에 성공하였습니다. 인증번호를 확인해주세요."
                    }
                }
            }
        },
        400: {
            'description': '잘못된 요청',
            'examples': {
                'Invalid Data': {
                    'value': {
                        "email": [
                            "user with this email already exists."
                        ],
                        "username": [
                            "A user with that username already exists."
                        ]
                    }
                }
            }
        }
    }
)
class SignUpView(generics.CreateAPIView):
    parser_classes = [JSONParser, FormParser]
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'signup'

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


@extend_schema(
    tags=["사용자"],
    summary="로그인",
    description="이메일과 비밀번호를 사용하여 로그인하고 JWT 토큰(Access, Refresh)을 발급받습니다.",
    request=CustomTokenObtainPairSerializer,
    responses={
        200: {
            'description': '로그인 성공',
            'examples': {
                'Success': {
                    'value': {
                        "isSuccess": True,
                        "message": "로그인에 성공했습니다.",
                        "username": "testuser",
                        "semester": 1,
                        "is_staff": False,
                        "refresh": "your_refresh_token",
                        "access": "your_access_token"
                    }
                }
            }
        },
        401: {
            'description': '인증 실패',
            'examples': {
                'User Not Found': {
                    'value': {
                        "isSuccess": False,
                        "errorCode": "USER_NOT_FOUND",
                        "message": "존재하지 않는 이메일입니다."
                    }
                },
                'Invalid Password': {
                    'value': {
                        "isSuccess": False,
                        "errorCode": "INVALID_PASSWORD",
                        "message": "비밀번호가 올바르지 않습니다."
                    }
                },
                'Account Not Verified': {
                    'value': {
                        "isSuccess": False,
                        "errorCode": "ACCOUNT_NOT_VERIFIED",
                        "message": "이메일 인증이 완료되지 않았습니다. 이메일을 확인해주세요."
                    }
                }
            }
        }
    }
)
class SignInView(TokenObtainPairView):
    parser_classes = [JSONParser, FormParser]
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'signin'

    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenRefreshView(APIView):
    @extend_schema(
        tags=["사용자"],
        summary="JWT 토큰 재발급",
        description="""**Refresh 토큰을 사용하여 새로운 Access 토큰을 발급받습니다.** 
        
- 요청 본문에 유효한 `refresh` 토큰을 포함해야 합니다.
- 성공 시, 새로운 `access` 토큰과 새로운 `refresh` 토큰이 반환됩니다.
- 보안을 위해 한 번 사용된 리프레시 토큰은 만료 처리되고 새로운 리프레시 토큰이 발급됩니다. 클라이언트는 이 새로운 리프레시 토큰을 저장하여 사용해야 합니다.""",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "string",
                        "description": "The refresh token."
                    }
                },
                "required": ["refresh"]
            }
        },
        responses={
            200: OpenApiExample(
                'Successful Response',
                summary='A successful response.',
                description='새로운 토큰이 성공적으로 반환되었습니다.',
                value={
                    "isSuccess": True,
                    "message": "토큰이 성공적으로 재발급되었습니다.",
                    "access": "new_access_token_string",
                    "refresh": "new_refresh_token_string",
                }
            ),
            400: {"description": "Bad Request - refresh 토큰이 제공되지 않음"},
            401: {"description": "Unauthorized - 제공된 토큰이 유효하지 않거나 만료됨"}
        }
    )
    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return Response({"error": "Refresh token is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            old_token = RefreshToken(refresh_token)

            # simplejwt의 RefreshToken(...) 생성자는 서명/만료만 검증하고 blacklist는 확인하지 않는다.
            # 탈취 후 로그아웃된 토큰이 재사용되는 것을 막기 위해 jti로 명시 조회한다.
            from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
            jti = old_token.get('jti')
            if jti and BlacklistedToken.objects.filter(token__jti=jti).exists():
                raise AuthenticationFailed('Token is blacklisted', code='token_not_valid')

            user_id = old_token.get('user_id')

            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise AuthenticationFailed('User not found', code='user_not_found')

            if not user.is_active or not user.is_verified:
                try:
                    old_token.blacklist()
                except Exception:
                    pass
                raise AuthenticationFailed('Account disabled', code='account_disabled')

            # last_login 업데이트
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])

            # 새로운 리프레시 토큰 생성
            new_refresh_token = RefreshToken.for_user(user)

            try:
                old_token.blacklist()
            except AttributeError:
                pass

            response_data = {
                "isSuccess": True,
                "message": "토큰이 성공적으로 재발급되었습니다.",
                'access': str(new_refresh_token.access_token),
                'refresh': str(new_refresh_token),
                'username': user.username,
                'email': user.email,
                'semester': user.semester,
                'is_staff': user.is_staff,
            }
            
            return Response(response_data, status=status.HTTP_200_OK)

        except AuthenticationFailed as e:
            detail = e.detail if hasattr(e, 'detail') else str(e)
            return Response({"error": str(detail)}, status=status.HTTP_401_UNAUTHORIZED)
        except TokenError as e:
            return Response({"error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({"error": "An unexpected error occurred.", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=["사용자"],
    summary="이메일 인증",
    description="회원가입 후 이메일로 발송된 6자리 인증 코드를 사용하여 이메일 주소를 인증합니다.",
    request=EmailVerificationSerializer,
    responses={
        200: {
            'description': '인증 성공',
            'examples': {
                'Success': {
                    'value': {"message": "Email verified successfully."}
                },
                'Already Verified': {
                    'value': {"message": "This account is already verified."}
                }
            }
        },
        400: {
            'description': '잘못된 요청',
            'examples': {
                'Expired Code': {
                    'value': {"error": "Verification code has expired."}
                },
                'Invalid Code': {
                    'value': {"error": "Invalid verification code."}
                }
            }
        },
        404: {
            'description': '사용자를 찾을 수 없음',
            'examples': {
                'User Not Found': {
                    'value': {"error": "User not found"}
                }
            }
        }
    }
)
class EmailVerifyView(APIView):
    serializer_class = EmailVerificationSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'email_verify'

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        verifyCode = serializer.validated_data['verifyCode']

        # 사용자 존재/상태/코드 유효성을 구분하는 3-way 응답은 회원 enumeration을 허용하므로
        # 성공 여부 외에는 전부 동일한 400으로 통일한다.
        generic_error = Response(
            {"error": "인증 정보가 유효하지 않거나 만료되었습니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_error

        if user.is_verified:
            # 이미 인증됐다면 코드 존재 여부와 무관하게 성공 응답을 준다.
            return Response({"message": "Email verified successfully."}, status=status.HTTP_200_OK)

        try:
            verification_code_obj = EmailVerificationCode.objects.get(user=user)
        except EmailVerificationCode.DoesNotExist:
            return generic_error

        if (timezone.now() - verification_code_obj.created_at).total_seconds() > 300:
            verification_code_obj.delete()
            return generic_error

        if not check_password(verifyCode, verification_code_obj.code):
            verification_code_obj.attempt_count = models.F('attempt_count') + 1
            verification_code_obj.save(update_fields=['attempt_count'])
            verification_code_obj.refresh_from_db()
            if verification_code_obj.attempt_count >= MAX_VERIFICATION_ATTEMPTS:
                verification_code_obj.delete()
            return generic_error

        # 신규 가입 인증: 아직 한 번도 인증된 적 없는 계정만 활성화한다.
        # 관리자가 이미 인증된 계정을 비활성화(`is_active=False`)한 경우 위 `is_verified=True`
        # 분기에서 바로 성공 응답을 주므로 is_active에 손대지 않아 제재가 유지된다.
        user.is_verified = True
        user.is_active = True
        user.save(update_fields=['is_verified', 'is_active'])
        verification_code_obj.delete()
        return Response({"message": "Email verified successfully."}, status=status.HTTP_200_OK)


class ResendVerificationEmailView(APIView):
    serializer_class = EmailResendSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset_request'

    @extend_schema(
        tags=["사용자"],
        summary="인증 이메일 재전송",
        description="인증 이메일을 재전송합니다. 사용자가 인증 코드를 받지 못했거나 코드가 만료된 경우 사용됩니다. 존재 여부와 관계없이 동일한 응답을 반환합니다.",
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        generic_response = Response(
            {"message": "A new verification email has been sent if the account exists and is pending verification."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        if user.is_verified:
            return generic_response

        code = ''.join(random.choices(string.digits, k=6))
        hashed_code = make_password(code)

        EmailVerificationCode.objects.update_or_create(
            user=user,
            defaults={'code': hashed_code, 'created_at': timezone.now(), 'attempt_count': 0},
        )

        subject = '[JBIG] Your New Verification Code'
        message = f'Your new verification code is: {code}'
        send_mail(subject, message, None, [user.email])

        return generic_response


class LogoutView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["사용자"],
        summary="로그아웃",
        description="사용자를 로그아웃 처리합니다. 요청 본문에 제공된 리프레시 토큰을 블랙리스트에 추가하여 더 이상 사용할 수 없게 만듭니다.",
        request= {
            "application/json": {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "string",
                        "description": "블랙리스트에 추가할 리프레시 토큰"
                    }
                },
                "required": ["refresh"]
            }
        },
        responses={
            205: {"description": "로그아웃 성공"},
            400: {"description": "잘못된 요청 - 토큰이 유효하지 않거나 누락됨"}
        }
    )
    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
        except (KeyError, TypeError):
            return Response(status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # 본인 리프레시 토큰만 블랙리스트 처리한다.
        if token.get('user_id') != request.user.id:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            token.blacklist()
        except Exception:
            # 이미 블랙리스트됐거나 outstanding이 없는 경우 — 사용자 관점에선 성공.
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset_request'

    @extend_schema(
        tags=["사용자"],
        summary="비밀번호 재설정 인증코드 요청",
        description=(
            "이메일로 인증 코드를 요청하여 비밀번호 재설정을 시작합니다. "
            "사용자 열거 방지를 위해 이메일 존재 여부와 관계없이 동일한 200 응답을 반환합니다."
        ),
        request=PasswordResetRequestSerializer,
        responses={
            200: {"description": "이메일이 등록되어 있다면 인증 코드가 발송됩니다."},
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        generic_response = Response(
            {"message": "입력하신 이메일이 등록되어 있다면 인증 코드가 발송됩니다."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        code = ''.join(random.choices(string.digits, k=6))
        hashed_code = make_password(code)

        EmailVerificationCode.objects.update_or_create(
            user=user,
            defaults={'code': hashed_code, 'created_at': timezone.now(), 'attempt_count': 0},
        )

        subject = '[JBIG] 비밀번호 변경 인증 코드'
        message = f'요청하신 비밀번호 변경 인증 코드는 다음과 같습니다: {code}'
        send_mail(subject, message, None, [user.email])

        return generic_response


class VerifyPasswordCodeView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset_verify'

    @extend_schema(
        tags=["사용자"],
        summary="비밀번호 재설정 인증코드 확인",
        description=(
            "이메일로 전송된 인증 코드를 확인하고, "
            "비밀번호 재설정에 사용할 단기 토큰(reset_token)을 발급합니다. "
            "발급된 토큰은 10분 동안 유효하며 PasswordResetView 호출 시 필수입니다."
        ),
        request=VerifyPasswordCodeSerializer,
        responses={
            200: {"description": "인증 코드가 확인되었습니다. 응답 본문에 reset_token이 포함됩니다."},
            400: {"description": "잘못된 요청 또는 유효하지 않은 인증 코드"}
        }
    )
    def post(self, request, *args, **kwargs):
        serializer = VerifyPasswordCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email'].strip().lower()
        verification_code = serializer.validated_data['verification_code']

        # 사용자 열거 및 코드 상태 노출을 방지하기 위해 실패 경로 응답을 단일화한다.
        generic_error = Response(
            {"error": "인증 정보가 유효하지 않거나 만료되었습니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_error

        try:
            verification_code_obj = EmailVerificationCode.objects.get(user=user)
        except EmailVerificationCode.DoesNotExist:
            return generic_error

        if (timezone.now() - verification_code_obj.created_at).total_seconds() > 300:
            verification_code_obj.delete()
            return generic_error

        if not check_password(verification_code, verification_code_obj.code):
            verification_code_obj.attempt_count = models.F('attempt_count') + 1
            verification_code_obj.save(update_fields=['attempt_count'])
            verification_code_obj.refresh_from_db()
            if verification_code_obj.attempt_count >= MAX_VERIFICATION_ATTEMPTS:
                verification_code_obj.delete()
            return generic_error

        reset_token, expires_in = issue_reset_token(user, request=request)

        # 인증코드는 재설정 토큰으로 교체되므로 즉시 제거한다.
        verification_code_obj.delete()

        return Response(
            {
                "message": "인증 코드가 확인되었습니다.",
                "reset_token": reset_token,
                "expires_in": expires_in,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["사용자"],
        summary="새 비밀번호로 재설정",
        description="인증코드 확인 후 새로운 비밀번호를 설정합니다.",
        request=PasswordResetSerializer,
        responses={
            200: {"description": "비밀번호가 성공적으로 변경되었습니다."},
            400: {"description": "잘못된 요청"}
        }
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email'].strip().lower()
        reset_token = serializer.validated_data['reset_token']
        new_password = serializer.validated_data['new_password1']

        try:
            user = consume_reset_token(reset_token, expected_email=email)
        except ResetTokenError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            return Response({"error": e.messages}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.password_changed_at = timezone.now()
        user.save()

        # 인증 코드 삭제
        EmailVerificationCode.objects.filter(user=user).delete()

        # 비밀번호 변경 시 모든 리프레시 토큰 블랙리스트 처리하여 강제 로그아웃
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
        try:
            outstanding_tokens = OutstandingToken.objects.filter(user=user)
            for token_obj in outstanding_tokens:
                try:
                    token = RefreshToken(token_obj.token)
                    token.blacklist()
                except Exception:
                    # 이미 블랙리스트에 있거나 만료된 토큰은 무시
                    pass
        except Exception:
            # 블랙리스트 앱이 없거나 오류 발생 시 무시
            pass

        return Response({"message": "비밀번호가 성공적으로 변경되었습니다."},
                        status=status.HTTP_200_OK)

@extend_schema(
    tags=["사용자"],
    summary="사용자 프로필 조회",
    description="특정 사용자의 프로필 정보를 조회합니다. 요청한 사용자가 프로필의 주인인지 여부(is_self)와 총 게시글/댓글 수를 포함합니다.",
    parameters=[
        OpenApiParameter(
            name='user_id',
            type=str,
            location=OpenApiParameter.PATH,
            description="사용자 ID (이메일의 '@' 앞 부분)"
        )
    ],
    responses={
        200: OpenApiExample(
            'Successful Response',
            summary='A successful response.',
            description='사용자 프로필 정보가 성공적으로 반환되었습니다.',
            value={
                "username": "testuser",
                "email": "test@example.com",
                "semester": 1,
                "is_staff": False,
                "date_joined": "2025-08-17 10:00:00",
                "is_self": True,
                "post_count": 15,
                "comment_count": 42
            }
        )
    }
)
class UserProfileView(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        user_id = (self.kwargs['user_id'] or '').strip().lower()
        # 전북대 이메일 ID(@ 앞부분)에 해당하는 사용자를 정확히 매칭한다.
        # 접두 매칭(startswith)은 예: 'a'로 'abc@...'를 잡는 경로 불일치 및
        # 여러 도메인을 가진 중복 ID 선점 공격의 여지를 남긴다.
        obj = get_object_or_404(self.get_queryset(), email__iexact=f'{user_id}@jbnu.ac.kr')
        self.check_object_permissions(self.request, obj)
        return obj

class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["사용자"],
        summary="[마이페이지] 현재 비밀번호로 변경",
        description="**로그인된 사용자가 현재 비밀번호를 사용하여 새 비밀번호로 변경합니다.**\n- 마이페이지 등에서 사용됩니다.",
        request=PasswordChangeSerializer,
        responses={
            200: {"description": "비밀번호가 성공적으로 변경되었습니다."},
            400: {"description": "잘못된 요청 또는 기존 비밀번호가 일치하지 않음"},
        }
    )
    def post(self, request):
        user = request.user
        kst = pytz.timezone('Asia/Seoul')
        now = timezone.now().astimezone(kst)

        if user.password_changed_at:
            last_changed_kst = user.password_changed_at.astimezone(kst)
            if now.date() == last_changed_kst.date():
                return Response({"error": "비밀번호는 하루에 한 번만 변경할 수 있습니다."},
                                status=status.HTTP_400_BAD_REQUEST)

        serializer = PasswordChangeSerializer(data=request.data)
        if serializer.is_valid():
            if not user.check_password(serializer.validated_data['old_password']):
                return Response({"error": "기존 비밀번호가 올바르지 않습니다."},
                                status=status.HTTP_400_BAD_REQUEST)

            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError

            try:
                validate_password(serializer.validated_data['new_password1'], user=user)
            except ValidationError as e:
                return Response({"error": e.messages}, status=status.HTTP_400_BAD_REQUEST)

            user.set_password(serializer.validated_data['new_password1'])
            user.password_changed_at = timezone.now()
            user.save()

            # 비밀번호 변경 시 모든 리프레시 토큰 블랙리스트 처리하여 강제 로그아웃
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            try:
                outstanding_tokens = OutstandingToken.objects.filter(user=user)
                for token_obj in outstanding_tokens:
                    try:
                        token = RefreshToken(token_obj.token)
                        token.blacklist()
                    except Exception:
                        # 이미 블랙리스트에 있거나 만료된 토큰은 무시
                        pass
            except Exception:
                # 블랙리스트 앱이 없거나 오류 발생 시 무시
                pass

            return Response({"message": "비밀번호가 성공적으로 변경되었습니다."},
                            status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["사용자"],
    summary="공개 프로필 조회",
    description="이메일 ID(@ 앞부분)로 사용자의 공개 프로필을 조회합니다. 로그인 없이 접근 가능합니다.",
    parameters=[
        OpenApiParameter(
            name='username',
            type=str,
            location=OpenApiParameter.PATH,
            description="사용자 ID (이메일의 '@' 앞 부분, 예: bjl5029)"
        )
    ]
)
class PublicProfileView(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = PublicProfileSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        username = (self.kwargs['username'] or '').strip().lower()
        obj = get_object_or_404(self.get_queryset(), email__iexact=f'{username}@jbnu.ac.kr')
        return obj


@extend_schema(
    tags=["사용자"],
    summary="프로필(Resume) 수정",
    description="본인의 프로필 정보(resume)를 수정합니다.",
    request=ResumeUpdateSerializer
)
class ResumeUpdateView(generics.UpdateAPIView):
    queryset = User.objects.all()
    serializer_class = ResumeUpdateSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


@extend_schema(
    tags=["사용자"],
    summary="프로필 블록 수정",
    description="본인의 프로필 블록 데이터를 수정합니다.",
    request=ProfileBlocksUpdateSerializer
)
class ProfileBlocksUpdateView(generics.UpdateAPIView):
    queryset = User.objects.all()
    serializer_class = ProfileBlocksUpdateSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


@extend_schema(
    tags=["사용자"],
    summary="회원 탈퇴",
    description="현재 로그인된 사용자의 계정을 삭제합니다. 이 작업은 되돌릴 수 없습니다.",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "password": {
                    "type": "string",
                    "description": "현재 비밀번호 확인"
                }
            },
            "required": ["password"]
        }
    },
    responses={
        200: {"description": "회원 탈퇴 성공"},
        400: {"description": "잘못된 요청 또는 비밀번호 불일치"},
        401: {"description": "인증되지 않은 사용자"}
    }
)
class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        password = request.data.get('password')

        if not password:
            return Response(
                {"error": "비밀번호를 입력해주세요."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 비밀번호 확인
        if not user.check_password(password):
            return Response(
                {"error": "비밀번호가 올바르지 않습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 모든 리프레시 토큰 블랙리스트 처리
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
        try:
            outstanding_tokens = OutstandingToken.objects.filter(user=user)
            for token_obj in outstanding_tokens:
                try:
                    token = RefreshToken(token_obj.token)
                    token.blacklist()
                except Exception:
                    pass
        except Exception:
            pass

        # 사용자 계정 삭제
        user.delete()

        return Response(
            {"message": "회원 탈퇴가 완료되었습니다."},
            status=status.HTTP_200_OK
        )
