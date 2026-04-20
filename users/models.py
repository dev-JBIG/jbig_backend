from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_active', False)

        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, username, password, **extra_fields)

class User(AbstractUser):
    # AbstractUser의 first_name, last_name 필드 제거
    first_name = None
    last_name = None

    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150)
    semester = models.PositiveIntegerField(
        verbose_name='기수',
        null=True,
        blank=True,
        help_text='예 : 1기면 1'
    )
    is_verified = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    resume = models.TextField(blank=True, default='', verbose_name='자기소개')
    profile_blocks = models.JSONField(default=list, blank=True, verbose_name='프로필 블록')

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'user'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'
        unique_together = [('username', 'semester')]

    def __str__(self):
        return self.email

class EmailVerificationCode(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='verification_code')
    code = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'email_verification_code'
        verbose_name = '이메일 인증 코드'
        verbose_name_plural = '이메일 인증 코드 목록'

    def __str__(self):
        return f'Verification code for {self.user.email}'

class PasswordResetToken(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_tokens',
    )
    token_hash = models.CharField(max_length=64, db_index=True, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_ip = models.GenericIPAddressField(null=True, blank=True)
    created_ua = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'password_reset_token'
        verbose_name = '비밀번호 재설정 토큰'
        verbose_name_plural = '비밀번호 재설정 토큰 목록'
        indexes = [
            models.Index(fields=['expires_at']),
            models.Index(fields=['user', 'used_at']),
        ]

    def __str__(self):
        return f'PasswordResetToken(user={self.user_id}, used={self.used_at is not None})'