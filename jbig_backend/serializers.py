import logging

from rest_framework import serializers
from .models import CalendarEvent, Popup
from .storage import generate_presigned_download_url

logger = logging.getLogger(__name__)


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
    source_post_id = serializers.IntegerField(source='source_post.id', read_only=True)
    source_board_id = serializers.IntegerField(source='source_post.board.id', read_only=True)
    auto_generated = serializers.SerializerMethodField()

    class Meta:
        model = Popup
        fields = [
            'id', 'title', 'content', 'image_url', 'image_path', 'start_date', 'end_date', 
            'is_active', 'created_at', 'updated_at', 
            'created_by', 'created_by_username', 'order',
            'source_post_id', 'source_board_id', 'auto_generated'
        ]
        read_only_fields = [
            'created_at', 'updated_at', 'created_by', 'image_url',
            'source_post_id', 'source_board_id', 'auto_generated'
        ]
    
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
        """NCP 경로를 Presigned URL로 변환 (로컬이면 /media/ URL)"""
        if not obj.image_url:
            return None
        return generate_presigned_download_url(obj.image_url)

    def get_auto_generated(self, obj):
        return obj.source_post_id is not None

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
