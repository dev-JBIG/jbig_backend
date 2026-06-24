#!/usr/bin/env python3
"""
NCP Object Storage → Cloudflare R2 마이그레이션 스크립트.

소스(NCP)의 모든 객체를 대상(R2) 버킷으로 복사한다.
- 멱등(idempotent): 대상에 같은 크기의 객체가 이미 있으면 건너뛴다.
- ContentType 보존.
- 대용량도 안전하게 스트리밍 복사.

환경변수 (소스 = NCP):
    NCP_ENDPOINT_URL, NCP_ACCESS_KEY_ID, NCP_SECRET_KEY, NCP_BUCKET_NAME
    NCP_REGION_NAME            (선택, 기본 'kr-standard')

환경변수 (대상 = R2):
    R2_ENDPOINT_URL            예) https://<accountid>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID, R2_SECRET_KEY, R2_BUCKET_NAME

옵션:
    --prefix uploads/         지정 prefix만 복사 (기본: 전체)
    --dry-run                 실제 복사 없이 대상/스킵만 출력
    --overwrite               크기가 같아도 무조건 다시 복사

사용 예:
    python scripts/migrate_ncp_to_r2.py --dry-run
    python scripts/migrate_ncp_to_r2.py
    python scripts/migrate_ncp_to_r2.py --prefix uploads/2025/
"""
import argparse
import os
import sys

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def _env(name: str, required: bool = True, default: str | None = None) -> str | None:
    val = os.getenv(name, default)
    if required and not val:
        sys.exit(f"환경변수 {name} 가 필요합니다.")
    return val


def make_client(endpoint, access_key, secret_key, region):
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
            region_name=region,
        ),
    )


def dest_size(client, bucket, key):
    """대상에 객체가 있으면 크기를, 없으면 None을 반환."""
    try:
        meta = client.head_object(Bucket=bucket, Key=key)
        return meta.get('ContentLength')
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise


def main():
    parser = argparse.ArgumentParser(description='NCP Object Storage → Cloudflare R2 복사')
    parser.add_argument('--prefix', default='', help='복사할 key prefix (기본: 전체)')
    parser.add_argument('--dry-run', action='store_true', help='실제 복사 없이 계획만 출력')
    parser.add_argument('--overwrite', action='store_true', help='크기가 같아도 다시 복사')
    args = parser.parse_args()

    src = make_client(
        _env('NCP_ENDPOINT_URL'),
        _env('NCP_ACCESS_KEY_ID'),
        _env('NCP_SECRET_KEY'),
        _env('NCP_REGION_NAME', required=False, default='kr-standard'),
    )
    src_bucket = _env('NCP_BUCKET_NAME')

    dst = make_client(
        _env('R2_ENDPOINT_URL'),
        _env('R2_ACCESS_KEY_ID'),
        _env('R2_SECRET_KEY'),
        'auto',
    )
    dst_bucket = _env('R2_BUCKET_NAME')

    print(f"소스 : {src_bucket}  →  대상 : {dst_bucket}")
    print(f"prefix={args.prefix or '(전체)'}  dry_run={args.dry_run}  overwrite={args.overwrite}\n")

    paginator = src.get_paginator('list_objects_v2')
    copied = skipped = failed = total = 0
    copied_bytes = 0

    for page in paginator.paginate(Bucket=src_bucket, Prefix=args.prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            # 레거시 역슬래시 key는 대상에서 '/'로 정규화 (공개 URL 호환)
            dst_key = key.replace('\\', '/')
            size = obj['Size']
            total += 1

            if not args.overwrite:
                existing = dest_size(dst, dst_bucket, dst_key)
                if existing == size:
                    skipped += 1
                    print(f"  SKIP  {dst_key}  ({size} B, 이미 존재)")
                    continue

            if args.dry_run:
                copied += 1
                tag = "  (정규화)" if dst_key != key else ""
                print(f"  COPY* {dst_key}  ({size} B)   [dry-run]{tag}")
                continue

            try:
                head = src.head_object(Bucket=src_bucket, Key=key)
                body = src.get_object(Bucket=src_bucket, Key=key)['Body']
                extra = {}
                if head.get('ContentType'):
                    extra['ContentType'] = head['ContentType']
                dst.upload_fileobj(body, dst_bucket, dst_key, ExtraArgs=extra or None)
                copied += 1
                copied_bytes += size
                print(f"  COPY  {dst_key}  ({size} B)")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  FAIL  {key}: {e}", file=sys.stderr)

    print(
        f"\n완료. 전체 {total}개 | 복사 {copied} "
        f"({copied_bytes / 1024 / 1024:.1f} MB) | 스킵 {skipped} | 실패 {failed}"
    )
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
