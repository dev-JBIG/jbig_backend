import logging
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

from rest_framework import serializers
from .models import CalendarEvent, Popup

logger = logging.getLogger(__name__)

# Thread-local storage for S3 client
import threading
_thread_local = threading.local()


def get_s3_client():
    """Thread-local S3 클라이언트 반환"""
    if not hasattr(_thread_local, 's3_client'):
        _thread_local.s3_client = boto3.client(
            's3',
            endpoint_url=settings.NCP_ENDPOINT_URL,
            aws_access_key_id=settings.NCP_ACCESS_KEY_ID,
            aws_secret_access_key=settings.NCP_SECRET_KEY,
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, region_name=settings.NCP_REGION_NAME)
        )
    return _thread_local.s3_client


class CalendarEventSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = CalendarEvent
        fields = ['id', 'author', 'title', 'start', 'end', 'allDay', 'color', 'description']


class PopupSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    image_url = serializers.SerializerMethodField()
    image_path = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    content = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Popup
        fields = [
            'id', 'title', 'content', 'image_url', 'image_path', 'start_date', 'end_date', 
            'is_active', 'created_at', 'updated_at', 
            'created_by', 'created_by_username', 'order'
        ]
        read_only_fields = ['created_at', 'updated_at', 'created_by', 'image_url']
    
    def validate(self, data):
        """내용 또는 이미지 중 하나는 필수"""
        content = data.get('content', '').strip()
        image_path = data.get('image_path', '').strip()
        
        # 생성 시에만 검증 (수정 시에는 기존 값이 있을 수 있음)
        if not self.instance:
            if not content and not image_path:
                raise serializers.ValidationError("내용 또는 이미지 중 하나는 입력해야 합니다.")
        
        return data

    def get_image_url(self, obj):
        """NCP 경로를 Presigned URL로 변환"""
        if not obj.image_url:
            return None
        
        # 이미 full URL인 경우 (하위 호환성)
        if obj.image_url.startswith('http'):
            return obj.image_url
        
        # NCP key 경로인 경우 Presigned URL 생성
        if obj.image_url.startswith('uploads/'):
            try:
                s3_client = get_s3_client()
                presigned_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': settings.NCP_BUCKET_NAME,
                        'Key': obj.image_url
                    },
                    ExpiresIn=3600  # 1시간
                )
                return presigned_url
            except Exception as e:
                logger.error(f"팝업 이미지 Presigned URL 생성 실패 (Key: {obj.image_url}): {e}")
                return None
        
        return None

    def create(self, validated_data):
        # image_path를 image_url 필드에 저장
        image_path = validated_data.pop('image_path', None)
        if image_path:
            validated_data['image_url'] = image_path
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # image_path를 image_url 필드에 저장
        image_path = validated_data.pop('image_path', None)
        if image_path is not None:  # None이 아닌 경우만 업데이트 (빈 문자열 포함)
            validated_data['image_url'] = image_path
        return super().update(instance, validated_data)