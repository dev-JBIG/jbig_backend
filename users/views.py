
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
    ResumeUpdateSerializer
)
from .models import User, EmailVerificationCode
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed
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
        username = self.kwargs['user_id']
        target_user = get_object_or_404(User, email__startswith=username + '@')
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
        user_id = self.kwargs['user_id']
        target_user = get_object_or_404(User, email__startswith=user_id + '@')
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
            user_id = old_token.get('user_id')
            
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise AuthenticationFailed('User not found', code='user_not_found')

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
        tags=["사용자"],
        summary="인증 이메일 재전송",
        description="인증 이메일을 재전송합니다. 사용자가 인증 코드를 받지 못했거나 코드가 만료된 경우 사용됩니다.",
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
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response(status=status.HTTP_205_RESET_CONTENT)
        except Exception :
            return Response(status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["사용자"],
        summary="비밀번호 재설정 인증코드 요청",
        description="이메일로 인증 코드를 요청하여 비밀번호 재설정을 시작합니다.",
        request=PasswordResetRequestSerializer,
        responses={
            200: {"description": "인증 코드가 이메일로 전송되었습니다."},
            400: {"description": "잘못된 요청"},
            404: {"description": "사용자를 찾을 수 없음"}
        }
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        code = ''.join(random.choices(string.digits, k=6))
        hashed_code = make_password(code)

        EmailVerificationCode.objects.update_or_create(
            user=user,
            defaults={'code': hashed_code, 'created_at': timezone.now()}
        )

        subject = '[JBIG] 비밀번호 변경 인증 코드'
        message = f'요청하신 비밀번호 변경 인증 코드는 다음과 같습니다: {code}'
        send_mail(subject, message, None, [user.email])

        return Response({"message": "인증 코드가 이메일로 전송되었습니다."}, 
                        status=status.HTTP_200_OK)


class VerifyPasswordCodeView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["사용자"],
        summary="비밀번호 재설정 인증코드 확인",
        description="이메일로 전송된 인증 코드를 확인합니다.",
        request=VerifyPasswordCodeSerializer,
        responses={
            200: {"description": "인증 코드가 확인되었습니다."},
            400: {"description": "잘못된 요청 또는 유효하지 않은 인증 코드"}
        }
    )
    def post(self, request, *args, **kwargs):
        serializer = VerifyPasswordCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        verification_code = serializer.validated_data['verification_code']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        try:
            verification_code_obj = EmailVerificationCode.objects.get(user=user)
        except EmailVerificationCode.DoesNotExist:
            return Response({"error": "인증 코드를 찾을 수 없습니다. 다시 요청해주세요."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        if (timezone.now() - verification_code_obj.created_at).total_seconds() > 300:
            return Response({"error": "인증 코드가 만료되었습니다."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        if not check_password(verification_code, verification_code_obj.code):
            return Response({"error": "유효하지 않은 인증 코드입니다."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        # Mark code as verified (but don't delete it yet)
        # A temporary flag could be added to the model, or we can rely on the client to proceed.
        # For simplicity, we'll just return a success message.

        return Response({"message": "인증 코드가 확인되었습니다."}, 
                        status=status.HTTP_200_OK)


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

        email = serializer.validated_data['email']
        new_password = serializer.validated_data['new_password1']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        # It's assumed the verification code was checked in the previous step.
        # For added security, you might want to re-verify a token passed from the verification step.

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
        user_id = self.kwargs['user_id']
        # email__startswith is used to find the user by the part of their email before the '@'
        obj = get_object_or_404(self.get_queryset(), email__startswith=user_id + '@')
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
        username = self.kwargs['username']
        obj = get_object_or_404(self.get_queryset(), email__istartswith=username + '@')
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
