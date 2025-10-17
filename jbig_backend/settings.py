from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

# --- Helpers for reading env vars ---
def get_env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def get_env_list(key: str, default: list[str] | None = None) -> list[str]:
    val = os.getenv(key)
    if not val:
        return [] if default is None else default
    return [item.strip() for item in val.split(',') if item.strip()]

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY')

# Debug toggle
DEBUG = get_env_bool('DEBUG', True)

# Hosts / CORS
ALLOWED_HOSTS = get_env_list('ALLOWED_HOSTS', ['*'])

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 3rd party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'corsheaders', # Add corsheaders

    # local apps
    'users',
    'boards',
    'jbig_backend',
    'html_serving',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', # Add corsheaders middleware
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'jbig_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'jbig_backend.wsgi.application'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('APP_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('EMAIL_HOST_USER')


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE'),
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'ko-kr'

TIME_ZONE = 'Asia/Seoul'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = os.getenv('STATIC_URL', 'static/')

MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
_MEDIA_ROOT = os.getenv('MEDIA_ROOT')
MEDIA_ROOT = Path(_MEDIA_ROOT) if _MEDIA_ROOT else BASE_DIR / 'media'

# App content paths configurable via environment
CONTENT_NOTION_SUBDIR = os.getenv('CONTENT_NOTION_SUBDIR', 'notion')
CONTENT_AWARDS_SUBDIR = os.getenv('CONTENT_AWARDS_SUBDIR', 'awards')
CONTENT_AWARD_HTML_FILENAME = os.getenv('CONTENT_AWARD_HTML_FILENAME', 'Awards 24c0b4f89da28059b565cbf910e6d6ad.html')
CONTENT_BANNER_SUBPATH = os.getenv('CONTENT_BANNER_SUBPATH', 'banner/banner.jpg')

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'users.User'

# CORS settings
CORS_ALLOW_CREDENTIALS = get_env_bool('CORS_ALLOW_CREDENTIALS', True)
# 개발 환경에서는 모든 출처를 허용합니다.
# 운영 환경에서는 보안을 위해 특정 도메인 목록을 사용하는 것이 좋습니다.
CORS_ALLOW_ALL_ORIGINS = get_env_bool('CORS_ALLOW_ALL_ORIGINS', True)

# If not allowing all origins, allow specific origins from env (comma-separated)
CORS_ALLOWED_ORIGINS = get_env_list('CORS_ALLOWED_ORIGINS', [])

CORS_ALLOW_HEADERS = [
    'Accept',
    'Accept-Language',
    'Content-Language',
    'Content-Type',
    'Authorization',
]

# CSRF trusted origins (comma-separated, e.g., https://example.com,https://www.example.com)
CSRF_TRUSTED_ORIGINS = get_env_list('CSRF_TRUSTED_ORIGINS', [])

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema', # Add this line
    'DEFAULT_PAGINATION_CLASS': 'jbig_backend.pagination.CustomPagination',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'JBIG 백엔드 API',
    'DESCRIPTION': 'JBIG 프로젝트 백엔드 API 문서입니다.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_SETTINGS': {
        'DEFAULT_MODEL_RENDERING': 'example',
        'DEFAULT_MODELS_EXPANSION': -1,
        'DEFAULT_MODEL_DEPTH': -1,
        'DOC_EXPANSION': 'none',
        'PERSIST_AUTHORIZATION': True,
        'DISPLAY_REQUEST_DURATION': True,
    },
    'TAGS': [
        {'name': '사용자', 'description': '사용자 인증 및 회원 정보 관련 API'},
        {'name': '게시판', 'description': '게시판 및 게시글 관련 API'},
        {'name': '댓글', 'description': '게시글 댓글 관련 API'},
        {'name': '파일', 'description': '파일 업로드 및 관리 API'},
    ],
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
}

_ACCESS_TOKEN_HOURS = int(os.getenv('ACCESS_TOKEN_HOURS', '1'))
_REFRESH_TOKEN_DAYS = int(os.getenv('REFRESH_TOKEN_DAYS', '1'))

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=_ACCESS_TOKEN_HOURS),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=_REFRESH_TOKEN_DAYS),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',

    'JTI_CLAIM': 'jti',

    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}
