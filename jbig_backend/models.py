from django.db import models
from django.conf import settings


class SiteSettings(models.Model):
    key = models.CharField(max_length=100, unique=True, primary_key=True)
    value = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'site_settings'
        verbose_name = '사이트 설정'
        verbose_name_plural = '사이트 설정'

    def __str__(self):
        return f"{self.key}: {self.value[:50]}"

    @classmethod
    def get(cls, key, default=''):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value):
        obj, _ = cls.objects.update_or_create(key=key, defaults={'value': value})
        return obj


class CalendarEvent(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    allDay = models.BooleanField(default=False)
    color = models.CharField(max_length=7)
    description = models.CharField(max_length=20)

    def __str__(self):
        return self.title


class Popup(models.Model):
    """업데이트 팝업 모델"""
    title = models.CharField(max_length=255, verbose_name='팝업 제목')
    content = models.TextField(verbose_name='팝업 내용')
    start_date = models.DateTimeField(verbose_name='시작 일시')
    end_date = models.DateTimeField(verbose_name='종료 일시')
    is_active = models.BooleanField(default=True, verbose_name='활성 여부')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성 일시')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정 일시')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='작성자'
    )
    order = models.IntegerField(default=0, verbose_name='표시 순서')

    class Meta:
        db_table = 'popups'
        verbose_name = '팝업'
        verbose_name_plural = '팝업'
        ordering = ['order', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.start_date.strftime('%Y-%m-%d')} ~ {self.end_date.strftime('%Y-%m-%d')})"