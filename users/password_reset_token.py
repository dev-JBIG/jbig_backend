import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import PasswordResetToken, User

RESET_TOKEN_TTL_SECONDS = 600


class ResetTokenError(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")[:1024] or None


@transaction.atomic
def issue_reset_token(user: User, request=None) -> tuple[str, int]:
    # 같은 사용자의 기존 미사용 토큰은 즉시 무효화하여 유출 시 노출 창을 좁힌다.
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    raw = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        token_hash=_hash(raw),
        expires_at=timezone.now() + timedelta(seconds=RESET_TOKEN_TTL_SECONDS),
        created_ip=_client_ip(request) if request is not None else None,
        created_ua=_user_agent(request) if request is not None else None,
    )
    return raw, RESET_TOKEN_TTL_SECONDS


@transaction.atomic
def consume_reset_token(token: str, expected_email: str) -> User:
    try:
        record = (
            PasswordResetToken.objects.select_for_update()
            .select_related("user")
            .get(token_hash=_hash(token))
        )
    except PasswordResetToken.DoesNotExist:
        raise ResetTokenError("유효하지 않은 재설정 토큰입니다.")

    if record.user.email.lower() != (expected_email or '').strip().lower():
        raise ResetTokenError("재설정 토큰의 이메일이 일치하지 않습니다.")
    if record.used_at is not None:
        raise ResetTokenError("이미 사용된 재설정 토큰입니다.")
    if record.expires_at <= timezone.now():
        raise ResetTokenError("재설정 토큰이 만료되었습니다. 인증을 다시 진행해주세요.")

    record.used_at = timezone.now()
    record.save(update_fields=["used_at"])
    return record.user
