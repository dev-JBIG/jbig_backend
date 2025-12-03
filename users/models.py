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
    username = models.CharField(max_length=150, unique=True)
    semester = models.PositiveIntegerField(
        verbose_name='기수',
        null=True,
        blank=True,
        help_text='예 : 1기면 1'
    )
    is_verified = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    resume = models.TextField(blank=True, default='', verbose_name='자기소개')
    can_use_gpu = models.BooleanField(default=False, verbose_name='GPU 대여 권한')

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'user'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return self.email

class UserRefreshToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    refresh_token = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_refresh_token'
        verbose_name = '사용자 리프레시 토큰'
        verbose_name_plural = '사용자 리프레시 토큰 목록'
        unique_together = ('user', 'refresh_token')

class EmailVerificationCode(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='verification_code')
    code = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_verification_code'
        verbose_name = '이메일 인증 코드'
        verbose_name_plural = '이메일 인증 코드 목록'

    def __str__(self):
        return f'Verification code for {self.user.email}'