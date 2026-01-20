# Python 3.12 이미지 사용
FROM python:3.12

# 환경변수 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# 시스템 패키지 업데이트 및 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# postgresql-client: DB 클라이언트 설치
# libpq-dev: PostgreSQL 개발 패키지 설치
# gcc: C 컴파일러 설치
# && rm -rf /var/lib/apt/lists/*: 설치 후 불필요한 파일 정리

# requirements.txt 복사 및 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# 애플리케이션 코드 복사
COPY . .

# 정적 파일 디렉토리 생성
RUN mkdir -p staticfiles

# 정적 파일 수집 (빌드 시점에 수행)
RUN python manage.py collectstatic --noinput --settings=jbig_backend.settings || true

# non-root 유저 생성 및 권한 설정 (보안)
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# 포트 노출
# 배포할땐 변경
EXPOSE 8000

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/health/', timeout=5)" || exit 1

# Gunicorn으로 실행
CMD ["gunicorn", "jbig_backend.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]

