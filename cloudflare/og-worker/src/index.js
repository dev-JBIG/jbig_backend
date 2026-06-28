/**
 * jbig-og — 링크 미리보기(Open Graph) 메타데이터 수집 Worker
 *
 * 백엔드(Django)가 호출하는 서버↔서버 엔드포인트.
 *   GET /?url=<대상 URL>
 *   헤더: X-OG-Secret: <env.OG_SECRET 와 동일>
 *   응답: { title, description, image, siteName }
 *
 * 오리진 서버에서 직접 크롤링하지 않으려고 분리한 것:
 *  - egress IP 격리(오리진 IP 차단/평판 영향 없음)
 *  - SSRF 격리(엣지에서 실행 → 내부망/메타데이터 접근 불가) + 추가 호스트 가드
 *  - 문자셋 직접 디코딩으로 한글 깨짐 방지
 *  - Cache API로 URL별 캐싱
 */

const MAX_BYTES = 512 * 1024;      // 본문 최대 512KB
const FETCH_TIMEOUT_MS = 6000;     // 대상 사이트 fetch 타임아웃
const CACHE_TTL_SECONDS = 86400;   // 결과 캐시 1일

export default {
  async fetch(request, env, ctx) {
    if (request.method !== 'GET') {
      return json({ error: 'method not allowed' }, 405);
    }

    // 1) 호출 인증 (공유 시크릿)
    const secret = env.OG_SECRET || '';
    if (!secret || request.headers.get('X-OG-Secret') !== secret) {
      return json({ error: 'unauthorized' }, 401);
    }

    // 2) 대상 URL 파싱/검증
    const target = new URL(request.url).searchParams.get('url') || '';
    let parsed;
    try {
      parsed = new URL(target);
    } catch {
      return json({ error: 'invalid url' }, 400);
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return json({ error: 'unsupported scheme' }, 400);
    }
    if (isBlockedHost(parsed.hostname)) {
      return json({ error: 'blocked host' }, 400);
    }

    // 3) 캐시 조회 (대상 URL 기준)
    const cache = caches.default;
    const cacheKey = new Request('https://og.cache/' + encodeURIComponent(parsed.toString()));
    const cached = await cache.match(cacheKey);
    if (cached) return cached;

    // 4) 대상 사이트 fetch (타임아웃/리다이렉트/크기 제한)
    let result;
    try {
      result = await fetchOpenGraph(parsed.toString());
    } catch (e) {
      return json({ error: 'fetch failed', detail: String(e) }, 200); // best-effort
    }

    const resp = json(result, 200, {
      'Cache-Control': `public, max-age=${CACHE_TTL_SECONDS}`,
    });
    ctx.waitUntil(cache.put(cacheKey, resp.clone()));
    return resp;
  },
};

async function fetchOpenGraph(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, {
      method: 'GET',
      redirect: 'follow',
      signal: controller.signal,
      headers: {
        // 알려진 프리뷰 봇 형태로 차단 회피 + 연락처 명시
        'User-Agent': 'Mozilla/5.0 (compatible; JBIG-LinkPreview/1.0; +https://jbig.co.kr)',
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.1',
        'Accept-Language': 'ko,en;q=0.8',
      },
    });
  } finally {
    clearTimeout(timer);
  }

  const finalUrl = res.url || url;
  const contentType = (res.headers.get('Content-Type') || '').toLowerCase();
  if (!contentType.includes('text/html') && !contentType.includes('application/xhtml')) {
    return empty();
  }

  const bytes = await readCapped(res, MAX_BYTES);
  const charset = detectCharset(contentType, bytes);
  let html;
  try {
    html = new TextDecoder(charset, { fatal: false }).decode(bytes);
  } catch {
    html = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  }

  const head = html.slice(0, 200 * 1024); // 메타는 <head>에 있으므로 앞부분만
  const { byProp, byName } = parseMetaTags(head);

  const title =
    byProp['og:title'] || byName['twitter:title'] || titleTag(head) || '';
  const description =
    byProp['og:description'] || byName['twitter:description'] || byName['description'] || '';
  let image = byProp['og:image'] || byName['twitter:image'] || '';
  const siteName = byProp['og:site_name'] || byName['application-name'] || '';

  if (image) {
    try { image = new URL(image, finalUrl).toString(); } catch { /* keep as-is */ }
  }

  return {
    title: decodeEntities(title).trim(),
    description: decodeEntities(description).trim(),
    image: image.trim(),
    siteName: decodeEntities(siteName).trim(),
  };
}

// ── helpers ──────────────────────────────────────────────────────────

function empty() {
  return { title: '', description: '', image: '', siteName: '' };
}

function json(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...extraHeaders },
  });
}

async function readCapped(res, max) {
  if (!res.body) return new Uint8Array(0);
  const reader = res.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    size += value.length;
    if (size >= max) { try { await reader.cancel(); } catch {} break; }
  }
  const out = new Uint8Array(Math.min(size, max));
  let off = 0;
  for (const c of chunks) {
    if (off >= out.length) break;
    const take = Math.min(c.length, out.length - off);
    out.set(c.subarray(0, take), off);
    off += take;
  }
  return out;
}

function detectCharset(contentType, bytes) {
  // 1) HTTP 헤더의 charset
  const m = /charset=["']?([\w-]+)/i.exec(contentType);
  if (m) return normalizeCharset(m[1]);
  // 2) <meta charset> / <meta http-equiv content="...charset=..."> (앞부분만 ascii로 훑음)
  const head = new TextDecoder('ascii', { fatal: false }).decode(bytes.slice(0, 4096));
  const m2 = /<meta[^>]+charset=["']?([\w-]+)/i.exec(head);
  if (m2) return normalizeCharset(m2[1]);
  const m3 = /<meta[^>]+content=["'][^"']*charset=([\w-]+)/i.exec(head);
  if (m3) return normalizeCharset(m3[1]);
  // 3) 기본 utf-8
  return 'utf-8';
}

function normalizeCharset(cs) {
  const c = cs.toLowerCase();
  if (c === 'ms949' || c === 'ks_c_5601-1987' || c === 'cp949') return 'euc-kr';
  return c;
}

function parseMetaTags(html) {
  const byProp = {};
  const byName = {};
  const tags = html.match(/<meta\b[^>]*>/gi) || [];
  for (const tag of tags) {
    const content = attr(tag, 'content');
    if (content == null) continue;
    const prop = attr(tag, 'property');
    const name = attr(tag, 'name');
    if (prop) byProp[prop.toLowerCase()] = content;
    if (name) byName[name.toLowerCase()] = content;
  }
  return { byProp, byName };
}

function attr(tag, key) {
  const re = new RegExp('\\b' + key + '=(?:"([^"]*)"|\'([^\']*)\'|([^\\s">]+))', 'i');
  const m = re.exec(tag);
  if (!m) return null;
  return m[1] ?? m[2] ?? m[3] ?? '';
}

function titleTag(html) {
  const m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
  return m ? m[1] : '';
}

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', '#39': "'" };
function decodeEntities(s) {
  if (!s) return '';
  return s
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => safeCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeCodePoint(parseInt(d, 10)))
    .replace(/&([a-z0-9]+);/gi, (m, n) => (ENTITIES[n.toLowerCase()] ?? m));
}
function safeCodePoint(cp) {
  try { return String.fromCodePoint(cp); } catch { return ''; }
}

function isBlockedHost(hostname) {
  const h = (hostname || '').toLowerCase().replace(/\.$/, '');
  if (!h) return true;
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.internal') || h.endsWith('.local')) return true;
  // IPv4 리터럴
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) {
    const p = h.split('.').map(Number);
    if (p.some((n) => n > 255)) return true;
    if (p[0] === 0 || p[0] === 10 || p[0] === 127) return true;       // this-net / 사설 / 루프백
    if (p[0] === 169 && p[1] === 254) return true;                    // link-local + 클라우드 메타데이터
    if (p[0] === 172 && p[1] >= 16 && p[1] <= 31) return true;        // 사설
    if (p[0] === 192 && p[1] === 168) return true;                    // 사설
    if (p[0] === 100 && p[1] >= 64 && p[1] <= 127) return true;       // CGNAT
  }
  // IPv6 리터럴 (URL.hostname은 대괄호를 제거함)
  if (h.includes(':')) {
    if (h === '::1' || h === '::' || h.startsWith('fe80') || h.startsWith('fc') || h.startsWith('fd')) return true;
  }
  return false;
}
