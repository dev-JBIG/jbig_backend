import os
from uuid import uuid4
from django.db import models

def file_upload_path(instance, filename):
    """
    파일 업로드 경로를 생성합니다.
    경로: notion/{type}/{uuid}.{extension}
    """
    # 파일 확장자 추출
    extension = filename.split('.')[-1]
    # 고유한 파일명 생성 (UUID 사용)
    unique_filename = f"{uuid4()}.{extension}"
    # 인스턴스의 type에 따라 폴더 경로 결정
    return os.path.join('notion', instance.get_type_display().lower(), unique_filename)

class Notion(models.Model):
    """
    Notion 콘텐츠 모델
    - 교안(textbook), 공지(notice) 등을 저장합니다.
    """
    class NotionType(models.TextChoices):
        TEXTBOOK = 'TB', '교안'
        NOTICE = 'NT', '공지'

    type = models.CharField(
        max_length=2,
        choices=NotionType.choices,
        default=NotionType.TEXTBOOK,
        verbose_name='종류'
    )
    title = models.CharField(max_length=100, verbose_name='제목')
    html_content = models.FileField(upload_to=file_upload_path, verbose_name='HTML 파일')
    image = models.ImageField(upload_to=file_upload_path, verbose_name='이미지 파일')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    def __str__(self):
        return f'[{self.get_type_display()}] {self.title}'

    class Meta:
        verbose_name = '노션 콘텐츠'
        verbose_name_plural = '노션 콘텐츠 목록'
        ordering = ['-created_at']