"""
Notion 내부 API 프록시 — splitbee 대체 셀프 호스팅

Notion의 내부 API(loadPageChunk, syncRecordValues)를 호출하여
react-notion-x가 그대로 소비할 수 있는 ExtendedRecordMap 포맷을 반환한다.
공개 페이지만 접근 가능하며 API 키가 필요하지 않다.

결과는 메모리 캐시에 저장하여 반복 요청 시 빠르게 반환한다.
"""
import re
import time as _time
import threading
import requests
import logging

logger = logging.getLogger(__name__)

NOTION_API = 'https://www.notion.so/api/v3'
HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0',
}
REQUEST_TIMEOUT = 30

# 메모리 캐시
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5분


def _format_uuid(page_id: str) -> str:
    clean = re.sub(r'[^a-fA-F0-9]', '', page_id)
    if len(clean) != 32:
        return page_id
    return f'{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}'


def _notion_post(endpoint: str, body: dict, retries: int = 2) -> dict:
    url = f'{NOTION_API}/{endpoint}'
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=body, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = min(2 ** attempt, 5)
                logger.warning(f'Notion rate limited, waiting {wait}s')
                _time.sleep(wait)
                continue
            if attempt < retries:
                _time.sleep(1)
                continue
            raise Exception(f'Notion API {endpoint} returned {resp.status_code}')
        except requests.exceptions.Timeout:
            if attempt < retries:
                logger.warning(f'Notion {endpoint} timeout, retrying')
                continue
            raise
    return {}


def _merge_record_maps(target: dict, source: dict):
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(value, dict):
            target[key].update(value)


def _unwrap_nested_values(record_map: dict):
    for section_key in ('block', 'collection', 'collection_view', 'notion_user'):
        section = record_map.get(section_key, {})
        keys_to_delete = []
        for item_id, item in section.items():
            if not isinstance(item, dict):
                keys_to_delete.append(item_id)
                continue
            value = item.get('value')
            if value is None:
                keys_to_delete.append(item_id)
                continue
            if isinstance(value, dict) and 'value' in value and 'role' in value and isinstance(value['value'], dict):
                section[item_id] = value
        for k in keys_to_delete:
            del section[k]


def _build_record_map(page_id: str) -> dict:
    uuid = _format_uuid(page_id)
    merged = {}

    chunk_number = 0
    cursor = {'stack': []}

    while True:
        data = _notion_post('loadPageChunk', {
            'page': {'id': uuid},
            'limit': 100,
            'cursor': cursor,
            'chunkNumber': chunk_number,
            'verticalColumns': False,
        })

        _merge_record_maps(merged, data.get('recordMap', {}))

        next_cursor = data.get('cursor', {})
        if not next_cursor.get('stack', []):
            break
        cursor = next_cursor
        chunk_number += 1
        if chunk_number > 50:
            break

    _unwrap_nested_values(merged)

    for key in ('block', 'collection', 'collection_view', 'notion_user', 'collection_query', 'signed_urls'):
        merged.setdefault(key, {})
    merged.pop('space', None)

    return merged


def _refresh_cache(page_id: str):
    try:
        data = _build_record_map(page_id)
        with _cache_lock:
            _cache[page_id] = {'data': data, 'expires': _time.time() + CACHE_TTL}
        logger.info(f'Notion cache refreshed: {page_id} ({len(data.get("block", {}))} blocks)')
    except Exception as e:
        logger.error(f'Notion cache refresh failed: {page_id}: {e}')


def fetch_page(page_id: str) -> dict:
    with _cache_lock:
        cached = _cache.get(page_id)

    if cached:
        if _time.time() < cached['expires']:
            return cached['data']
        # 만료 → stale 반환 + 백그라운드 갱신
        threading.Thread(target=_refresh_cache, args=(page_id,), daemon=True).start()
        return cached['data']

    # 첫 요청 → 동기 빌드
    data = _build_record_map(page_id)
    with _cache_lock:
        _cache[page_id] = {'data': data, 'expires': _time.time() + CACHE_TTL}
    return data
