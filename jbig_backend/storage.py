"""
스토리지 유틸리티 — NCP Object Storage / 로컬 파일시스템 자동 전환

.env에 NCP 키가 있으면 NCP, 없으면 로컬 media/ 디렉토리를 사용한다.
"""
import os
import logging
import threading

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

# ── NCP S3 클라이언트 (thread-local) ──────────────────────────────
_thread_local = threading.local()


def get_s3_client():
    """NCP용 thread-local S3 클라이언트 반환"""
    if not hasattr(_thread_local, 's3_client'):
        _thread_local.s3_client = boto3.client(
            's3',
            endpoint_url=settings.NCP_ENDPOINT_URL,
            aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
            aws_secret_access_key=settings.NCP_SECRET_KEY,
            config=Config(
                signature_version='s3v4',
                s3={'addressing_style': 'path'},
                region_name=settings.NCP_REGION_NAME,
            ),
        )
    return _thread_local.s3_client


# ── 공용 인터페이스 ──────────────────────────────────────────────

def generate_presigned_upload_url(file_key: str, request=None, expires_in: int = 600) -> dict:
    """
    업로드용 URL + 메타 정보를 반환한다.

    로컬 모드: upload_url = http://localhost:8000/api/local-upload/<file_key>  (PUT)
    NCP 모드 : upload_url = presigned PUT URL
    """
    if settings.USE_LOCAL_STORAGE:
        path = f'/api/local-upload/{file_key}'
        # 프론트엔드가 절대 URL로 PUT 요청하므로, request에서 호스트를 가져와 절대 URL 생성
        if request:
            upload_url = request.build_absolute_uri(path)
        else:
            upload_url = f'http://localhost:8000{path}'
        public_url = request.build_absolute_uri(f'{settings.MEDIA_URL}{file_key}') if request else f'{settings.MEDIA_URL}{file_key}'
        return {
            'upload_url': upload_url,
            'file_key': file_key,
            'url': public_url,
        }

    s3_client = get_s3_client()
    upload_url = s3_client.generate_presigned_url(
        'put_object',
        Params={'Bucket': settings.NCP_BUCKET_NAME, 'Key': file_key},
        ExpiresIn=expires_in,
    )
    public_url = f"{settings.NCP_ENDPOINT_URL}/{settings.NCP_BUCKET_NAME}/{file_key}"
    return {
        'upload_url': upload_url,
        'file_key': file_key,
        'url': public_url,
    }


def generate_presigned_download_url(file_key: str, expires_in: int = 3600) -> str | None:
    """
    다운로드(조회)용 URL을 반환한다.
    """
    if not file_key:
        return None

    if settings.USE_LOCAL_STORAGE:
        return f'{settings.MEDIA_URL}{file_key}'

    if file_key.startswith('http'):
        return file_key

    try:
        s3_client = get_s3_client()
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': settings.NCP_BUCKET_NAME, 'Key': file_key},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        logger.error(f"Presigned URL 생성 실패 (Key: {file_key}): {e}")
        return None


def delete_file(file_key: str) -> bool:
    """파일 하나를 삭제한다."""
    if not file_key or not file_key.startswith('uploads/'):
        return False

    if settings.USE_LOCAL_STORAGE:
        path = os.path.join(settings.MEDIA_ROOT, file_key)
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"로컬 파일 삭제 완료: {file_key}")
            return True
        except OSError as e:
            logger.error(f"로컬 파일 삭제 실패 ({file_key}): {e}")
            return False

    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=settings.NCP_BUCKET_NAME, Key=file_key)
        logger.info(f"NCP 파일 삭제 완료: {file_key}")
        return True
    except ClientError as e:
        logger.error(f"NCP 파일 삭제 실패 (Key: {file_key}): {e}")
        return False


def delete_files(file_keys: set[str]) -> None:
    """여러 파일을 삭제한다."""
    for key in file_keys:
        delete_file(key)


def set_public_acl(file_key: str) -> bool:
    """파일에 public-read ACL을 설정한다. 로컬에서는 no-op."""
    if settings.USE_LOCAL_STORAGE:
        return True

    try:
        s3_client = get_s3_client()
        s3_client.put_object_acl(
            Bucket=settings.NCP_BUCKET_NAME, Key=file_key, ACL='public-read'
        )
        return True
    except ClientError as e:
        logger.error(f"ACL 적용 실패 (Key: {file_key}): {e}")
        return False


def file_exists(file_key: str) -> bool:
    """파일 존재 여부 확인."""
    if settings.USE_LOCAL_STORAGE:
        return os.path.exists(os.path.join(settings.MEDIA_ROOT, file_key))

    try:
        s3_client = get_s3_client()
        s3_client.head_object(Bucket=settings.NCP_BUCKET_NAME, Key=file_key)
        return True
    except ClientError:
        return False


def save_local_file(file_key: str, body: bytes) -> str:
    """로컬 media/ 디렉토리에 파일을 저장한다."""
    path = os.path.join(settings.MEDIA_ROOT, file_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(body)
    return path
