# jbig-og — 링크 미리보기 Worker

링크공유 게시판의 Open Graph(제목/설명/이미지) 수집을 오리진 서버 대신
Cloudflare Worker에서 처리한다. (egress IP 격리 · SSRF 격리 · 부하 방지 · 문자셋 정상 처리)

```
백엔드(Django) ──GET /?url=<대상>──▶ Worker ──fetch/파싱/캐싱──▶ 대상 사이트
                 헤더 X-OG-Secret              응답 { title, description, image, siteName }
```

## 배포

```bash
cd cloudflare/og-worker
npm install
npx wrangler login                 # Cloudflare 계정 로그인(브라우저)
npx wrangler secret put OG_SECRET  # 강력한 랜덤 문자열 입력 (백엔드와 동일 값 사용)
npx wrangler deploy
```

배포 후 출력되는 URL을 확인한다. 예:
```
https://jbig-og.<account>.workers.dev
```

## 백엔드 연동 (운영 서버 `shared/.env`)

```bash
OG_WORKER_URL=https://jbig-og.<account>.workers.dev
OG_WORKER_SECRET=<wrangler secret put 으로 넣은 값과 동일>
```
설정 후 백엔드 재시작(배포). 두 값이 비어 있으면 미리보기만 생략되고 링크 저장은 정상 동작한다.

## 빠른 점검

```bash
# 인증 없으면 401
curl -s "https://jbig-og.<account>.workers.dev/?url=https://example.com"
# 정상 호출
curl -s -H "X-OG-Secret: <시크릿>" \
  "https://jbig-og.<account>.workers.dev/?url=https://www.naver.com" | jq
```

## 동작 요약
- `X-OG-Secret` 헤더로 호출 인증 (오픈 프록시 악용 방지)
- 스킴/사설IP/메타데이터 호스트 차단(SSRF 가드)
- 타임아웃 6s, 본문 512KB 제한, `text/html` 만 파싱
- `Content-Type` → `<meta charset>` 순으로 문자셋 판별 후 `TextDecoder` 디코딩
  (utf-8/euc-kr 등 → 한글 깨짐 방지)
- og:* / twitter:* / `<title>` / description 추출, 상대 이미지 URL 절대화
- Cache API로 대상 URL별 1일 캐싱
