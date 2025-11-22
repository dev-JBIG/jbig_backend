from django.db import models


# [Deprecated] 레거시 모델 - Notion은 이제 splitbee 프록시 사용
# DB 스키마 호환성을 위해 유지
class Notion(models.Model):
    title = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512, unique=True)

    class Meta:
        verbose_name = '[Deprecated] Notion'
        verbose_name_plural = '[Deprecated] Notion 목록'

    def __str__(self):
        return self.title
