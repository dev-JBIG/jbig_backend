"""
스토리지 유틸리티 — S3 호환 오브젝트 스토리지(Cloudflare R2) / 로컬 파일시스템 자동 전환

USE_LOCAL_STORAGE=False 이면 R2(STORAGE_* 환경변수), True 이면 로컬 media/ 디렉토리를 사용한다.
"""
import os
import logging
import threading

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

# ── S3 호환 스토리지 클라이언트 (thread-local) ──────────────────────────────
_thread_local = threading.local()


def get_s3_client():
    """S3 호환 스토리지(Cloudflare R2)용 thread-local 클라이언트 반환"""
    if not hasattr(_thread_local, 's3_client'):
        _thread_local.s3_client = boto3.client(
            's3',
            endpoint_url=settings.STORAGE_ENDPOINT_URL,
            aws_access_key_id=settings.STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.STORAGE_SECRET_KEY,
            config=Config(
                signature_version='s3v4',
                s3={'addressing_style': 'path'},
                region_name=settings.STORAGE_REGION_NAME,
            ),
        )
    return _thread_local.s3_client


def public_media_url(file_key: str) -> str | None:
    """파일 key를 공개(CDN) URL로 변환한다.

    - 로컬               : /media/<key>
    - MEDIA_PUBLIC_BASE_URL 설정 시: <base>/<key>  (Cloudflare CDN 등 고정 URL → 캐시 가능)
    - 미설정 시          : <endpoint>/<bucket>/<key>  (기존 공개 URL 폴백)
    이미 http(s) URL이면 그대로 반환한다.
    """
    if not file_key:
        return None
    if file_key.startswith('http://') or file_key.startswith('https://'):
        return file_key
    # 레거시 역슬래시 key 정규화(공개 URL 경로에서 역슬래시는 브라우저가 '/'로 바꿔 깨짐)
    file_key = file_key.replace('\\', '/')
    if settings.USE_LOCAL_STORAGE:
        return f'{settings.MEDIA_URL}{file_key}'
    if settings.MEDIA_PUBLIC_BASE_URL:
        return f'{settings.MEDIA_PUBLIC_BASE_URL}/{file_key}'
    return f'{settings.STORAGE_ENDPOINT_URL}/{settings.STORAGE_BUCKET_NAME}/{file_key}'


# ── 공용 인터페이스 ──────────────────────────────────────────────

def generate_presigned_upload_url(file_key: str, request=None, expires_in: int = 600) -> dict:
    """
    업로드용 URL + 메타 정보를 반환한다.

    로컬 모드   : upload_url = http://localhost:8000/api/local-upload/<file_key>  (PUT)
    스토리지 모드: upload_url = presigned PUT URL
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
        Params={'Bucket': settings.STORAGE_BUCKET_NAME, 'Key': file_key},
        ExpiresIn=expires_in,
    )
    return {
        'upload_url': upload_url,
        'file_key': file_key,
        'url': public_media_url(file_key),
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
            Params={'Bucket': settings.STORAGE_BUCKET_NAME, 'Key': file_key},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        logger.error(f"Presigned URL 생성 실패 (Key: {file_key}): {e}")
        return None


def get_file_stream(file_key: str):
    """파일을 스트리밍하기 위한 (파일객체, content_type, content_length)를 반환한다.

    권한 게이트된 첨부 다운로드에서 사용한다. 백엔드가 직접 바이트를 흘려보내므로
    스토리지가 도메인 단위 공개여도 클라이언트에 원본 URL이 노출되지 않는다.
    로컬/스토리지 모두 지원하며, 실패 시 None을 반환한다.
    """
    if not file_key:
        return None

    if settings.USE_LOCAL_STORAGE:
        path = os.path.join(settings.MEDIA_ROOT, file_key)
        if not os.path.exists(path):
            return None
        return open(path, 'rb'), None, os.path.getsize(path)

    try:
        s3_client = get_s3_client()
        obj = s3_client.get_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=file_key)
        return obj['Body'], obj.get('ContentType'), obj.get('ContentLength')
    except ClientError as e:
        logger.error(f"파일 스트림 조회 실패 (Key: {file_key}): {e}")
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
        s3_client.delete_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=file_key)
        logger.info(f"스토리지 파일 삭제 완료: {file_key}")
        return True
    except ClientError as e:
        logger.error(f"스토리지 파일 삭제 실패 (Key: {file_key}): {e}")
        return False


def delete_files(file_keys: set[str]) -> None:
    """여러 파일을 삭제한다."""
    for key in file_keys:
        delete_file(key)


def set_public_acl(file_key: str) -> bool:
    """파일에 public-read ACL을 설정한다. 로컬/ACL 미지원 스토리지에서는 no-op."""
    if settings.USE_LOCAL_STORAGE:
        return True

    # R2 등 객체 ACL 미지원 스토리지: 공개는 도메인 단위로 처리되므로 no-op.
    if not settings.STORAGE_SUPPORTS_ACL:
        return True

    try:
        s3_client = get_s3_client()
        s3_client.put_object_acl(
            Bucket=settings.STORAGE_BUCKET_NAME, Key=file_key, ACL='public-read'
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
        s3_client.head_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=file_key)
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
