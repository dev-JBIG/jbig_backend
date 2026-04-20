import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings

RESET_TOKEN_PURPOSE = "pw_reset"
RESET_TOKEN_TTL_SECONDS = 600
RESET_TOKEN_ALGORITHM = "HS256"


class ResetTokenError(Exception):
    pass


def issue_reset_token(email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "purpose": RESET_TOKEN_PURPOSE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=RESET_TOKEN_ALGORITHM)


def decode_reset_token(token: str, expected_email: str) -> None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[RESET_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ResetTokenError("재설정 토큰이 만료되었습니다. 인증을 다시 진행해주세요.") from exc
    except jwt.InvalidTokenError as exc:
        raise ResetTokenError("유효하지 않은 재설정 토큰입니다.") from exc

    if payload.get("purpose") != RESET_TOKEN_PURPOSE:
        raise ResetTokenError("유효하지 않은 재설정 토큰입니다.")
    if payload.get("sub") != expected_email:
        raise ResetTokenError("재설정 토큰의 이메일이 일치하지 않습니다.")
