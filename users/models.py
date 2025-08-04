from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.conf import settings

class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = 'role'
        verbose_name = '역할'
        verbose_name_plural = '역할 목록'

    def __str__(self):
        return self.name

class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        
        role_name = extra_fields.pop('role', 'user')
        try:
            role = Role.objects.get(name=role_name)
        except Role.DoesNotExist:
            role = Role.objects.create(name=role_name)

        user = self.model(email=email, username=username, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        extra_fields['role'] = 'admin'
        
        return self.create_user(email, username, password, **extra_fields)

class User(AbstractUser):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, related_name='users')
    semester = models.PositiveIntegerField(
        verbose_name='기수',
        null=True,
        blank=True,
        help_text='예 : 1기면 1'
    )

    groups = None
    user_permissions = None

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'user'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return self.email

