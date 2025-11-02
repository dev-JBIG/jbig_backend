# JBIG web Backend 입니다

# 배포 설정 파일

이 폴더는 Django 애플리케이션을 프로덕션 서버에 배포하기 위한 설정 파일들을 포함합니다.

## 파일 목록

### `gunicorn.service`
Systemd 서비스 설정 파일입니다. Gunicorn을 시스템 서비스로 등록하여 자동 시작 및 관리가 가능하도록 합니다.

**주요 설정:**
- 서비스명: `gunicorn-jbig`
- 실행 포트: `3001`
- 워커 수: `3`
- 타임아웃: `60초`
- 자동 재시작: 활성화

**사용 방법:**
```bash
# 서비스 파일 복사
sudo cp deploy/gunicorn.service /etc/systemd/system/

# systemd 재로드
sudo systemctl daemon-reload

# 서비스 활성화 (부팅 시 자동 시작)
sudo systemctl enable gunicorn-jbig

# 서비스 시작
sudo systemctl start gunicorn-jbig

# 서비스 상태 확인
sudo systemctl status gunicorn-jbig

# 서비스 중지
sudo systemctl stop gunicorn-jbig

# 서비스 재시작
sudo systemctl restart gunicorn-jbig
```

### `jbig_backend.env.example`
환경 변수 템플릿 파일입니다. 실제 서버 환경에 맞게 수정하여 사용합니다.

**사용 방법:**
```bash
# 예시 파일을 참고하여 실제 환경 변수 파일 생성
sudo cp deploy/jbig_backend.env.example /etc/jbig_backend.env

# 환경 변수 파일 편집
sudo nano /etc/jbig_backend.env

# 파일 권한 설정 (보안)
sudo chmod 600 /etc/jbig_backend.env
```

**주요 환경 변수:**
- `DJANGO_DEBUG`: 디버그 모드 (프로덕션에서는 `False`)
- `DJANGO_SECRET_KEY`: Django 시크릿 키 (반드시 변경 필요)
- `DJANGO_ALLOWED_HOSTS`: 허용된 호스트 목록 (쉼표로 구분)
- `DATABASE_URL`: 데이터베이스 연결 문자열 (필요 시)

## 배포 체크리스트

배포 전 확인사항:

- [ ] 환경 변수 파일 생성 및 설정 (`/etc/jbig_backend.env`)
- [ ] `gunicorn.service` 파일의 경로 확인 (WorkingDirectory, ExecStart 경로)
- [ ] Gunicorn 서비스 등록 및 시작
- [ ] Nginx 설정 확인 및 리로드
- [ ] 방화벽 포트 오픈 확인 (3001, 80, 443)
- [ ] 데이터베이스 마이그레이션 실행
- [ ] 정적 파일 수집 (`python manage.py collectstatic`)

## 서비스 상태 확인

```bash
# Gunicorn 서비스 상태
sudo systemctl status gunicorn-jbig

# Gunicorn 프로세스 확인
ps aux | grep gunicorn

# 포트 리스닝 확인
sudo netstat -tlnp | grep :3001
# 또는
sudo ss -tlnp | grep :3001

# 서비스 로그 확인
sudo journalctl -u gunicorn-jbig -f
```

## 문제 해결

### 서비스가 시작되지 않을 때
1. 로그 확인: `sudo journalctl -u gunicorn-jbig -n 50`
2. 환경 변수 파일 경로 확인: `/etc/jbig_backend.env`
3. 작업 디렉토리 존재 여부 확인
4. 가상환경 경로 확인

### 포트가 사용 중일 때
```bash
# 포트 사용 프로세스 확인
sudo lsof -i :3001
# 또는
sudo fuser -k 3001/tcp
```

## 참고사항

- Gunicorn은 포트 `3001`에서 실행됩니다
- Nginx를 리버스 프록시로 사용하는 경우, `/etc/nginx/sites-available/` 설정 필요
- 프로덕션 환경에서는 `DEBUG=False`로 설정 필수
- `SECRET_KEY`는 반드시 강력한 랜덤 값으로 변경 필요
