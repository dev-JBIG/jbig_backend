# R2 + Cloudflare CDN 전환 가이드

NCP Object Storage(S3 호환)에서 **Cloudflare R2 + Cloudflare CDN**으로 전환하는 절차.
목적: 미디어 트래픽(egress) 비용 절감 + CDN 캐시 도입.

- **R2**: S3 호환 객체 스토리지. **egress(전송) 요금 0원**, 저장 ~$0.015/GB·월.
- **CDN**: R2 버킷에 커스텀 도메인(`cdn.jbig.co.kr`)을 연결하면 Cloudflare 엣지에서 자동 캐시.

읽기 URL이 `https://cdn.jbig.co.kr/<key>` 형태의 **고정 공개 URL**이 되어야 CDN 캐시가 동작한다.
이번 변경으로 백엔드의 모든 읽기 URL(게시글 이미지/첨부, 팝업, 마크다운)이 presigned가 아닌 고정 공개 URL로 나간다.

> 공개 범위: 업로드 key는 `uploads/<날짜>/<userId>/<uuid>.<ext>` 형태로 UUID 난수화되어 있어
> 사실상 "비공개 링크(unlisted)" 수준이다. 인증이 필요한 민감 자료에는 적합하지 않다.

---

## 1. Cloudflare 대시보드 작업 (직접)

1. **R2 버킷 생성**: R2 → Create bucket → 이름 예) `jbig-media`.
2. **API 토큰 발급**: R2 → Manage R2 API Tokens → *Object Read & Write*.
   - `Access Key ID`, `Secret Access Key`, 그리고 계정의 S3 endpoint
     (`https://<account_id>.r2.cloudflarestorage.com`)를 메모.
3. **커스텀 도메인 연결**: 버킷 → Settings → Public access → **Custom Domains** →
   `cdn.jbig.co.kr` 추가. (도메인이 Cloudflare DNS로 관리되고 있어야 자동으로 CNAME + 인증서 + 캐시 적용)
4. **캐시 규칙(선택)**: 기본 캐시로 충분하지만, 이미지 TTL을 늘리려면
   Caching → Cache Rules에서 `cdn.jbig.co.kr` 대상 Edge TTL을 길게(예: 30일) 설정.

> R2는 객체 단위 ACL이 없다. 공개는 위 커스텀 도메인 연결로 처리된다.
> 그래서 백엔드 `STORAGE_SUPPORTS_ACL=false` 로 둔다(아래).

---

## 2. 데이터 복사 (NCP → R2)

`scripts/migrate_ncp_to_r2.py` 사용. 소스(NCP)와 대상(R2) 양쪽 자격증명을 환경변수로 준다.

```bash
# 소스 = NCP (기존 .env 값)
export NCP_ENDPOINT_URL=https://kr.object.ncloudstorage.com
export NCP_ACCESS_KEY_ID=...        NCP_SECRET_KEY=...
export NCP_BUCKET_NAME=jbig         NCP_REGION_NAME=kr-standard

# 대상 = R2
export R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
export R2_ACCESS_KEY_ID=...         R2_SECRET_KEY=...
export R2_BUCKET_NAME=jbig-media

# 먼저 계획만 확인
python scripts/migrate_ncp_to_r2.py --dry-run
# 실제 복사 (멱등 — 다시 돌려도 안전)
python scripts/migrate_ncp_to_r2.py
```

배포 직전에 한 번 더 실행해 그 사이 새로 올라온 파일까지 동기화한다.

---

## 3. 백엔드 환경변수 교체

기존 `NCP_*` 는 그대로 두고(폴백·마이그레이션용), 아래 `STORAGE_*` / `MEDIA_*` 를 추가하면
런타임이 R2를 바라본다.

```bash
STORAGE_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
STORAGE_ACCESS_KEY_ID=...
STORAGE_SECRET_KEY=...
STORAGE_BUCKET_NAME=jbig-media
STORAGE_REGION_NAME=auto

# 읽기 URL을 CDN 고정 URL로 만든다 (CDN 캐시의 핵심)
MEDIA_PUBLIC_BASE_URL=https://cdn.jbig.co.kr

# R2는 객체 ACL 미지원
STORAGE_SUPPORTS_ACL=false
```

> `STORAGE_*` 를 비워두면 자동으로 기존 `NCP_*` 값으로 폴백하므로,
> 설정 전까지는 기존 동작이 그대로 유지된다(안전).

---

## 4. 프론트엔드 환경변수

배너 등 정적 미디어 베이스 URL:

```bash
REACT_APP_MEDIA_BASE_URL=https://cdn.jbig.co.kr
```

미설정 시 기존 NCP 퍼블릭 URL로 폴백한다. 빌드 후 배포.

---

## 5. 컷오버 & 검증

1. 마지막 동기화(`migrate_ncp_to_r2.py`) 재실행.
2. 백엔드/프론트 환경변수 적용 후 배포.
3. 검증:
   - 게시글 이미지/첨부, 팝업 배너가 `https://cdn.jbig.co.kr/...` 로 로드되는지.
   - 응답 헤더에 `cf-cache-status: HIT`(두 번째 요청부터) 가 찍히는지:
     ```bash
     curl -sI https://cdn.jbig.co.kr/static/banner.jpg | grep -i cf-cache-status
     ```
   - 새 글 작성 시 이미지 업로드/표시/미사용 정리가 정상인지.
4. 며칠 모니터링 후 NCP egress가 떨어지는지 확인 → 안정되면 NCP 버킷/키 정리.

## 롤백

`STORAGE_*` / `MEDIA_PUBLIC_BASE_URL` 환경변수를 제거(또는 NCP 값으로 교체)하고
프론트 `REACT_APP_MEDIA_BASE_URL` 을 비우면 기존 NCP 경로로 즉시 되돌아간다.
(원본은 복사 방식이라 NCP에 그대로 남아 있음)
