"""
Notion 내부 API 프록시 — splitbee 대체 셀프 호스팅

Notion의 내부 API(loadPageChunk, syncRecordValues)를 호출하여
react-notion-x가 그대로 소비할 수 있는 ExtendedRecordMap 포맷을 반환한다.
공개 페이지만 접근 가능하며 API 키가 필요하지 않다.
"""
import re
import time
import requests
import logging

logger = logging.getLogger(__name__)

NOTION_API = 'https://www.notion.so/api/v3'
HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0',
}
REQUEST_TIMEOUT = 30
MAX_CHUNKS = 50
MAX_MISSING_ROUNDS = 10
BLOCK_BATCH_SIZE = 100

RECORD_MAP_SECTIONS = ('block', 'collection', 'collection_view', 'notion_user')
RECORD_MAP_KEYS = (*RECORD_MAP_SECTIONS, 'collection_query', 'signed_urls')

_UUID_STRIP_RE = re.compile(r'[^a-fA-F0-9]')


class NotionAPIError(RuntimeError):
    pass


def _format_uuid(page_id: str) -> str:
    """하이픈 없는 32자 hex를 UUID 포맷(8-4-4-4-12)으로 변환"""
    clean = _UUID_STRIP_RE.sub('', page_id)
    if len(clean) != 32:
        return page_id
    return f'{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}'


def _notion_post(endpoint: str, body: dict, retries: int = 2) -> dict:
    """Notion API POST 요청 (재시도 포함)"""
    url = f'{NOTION_API}/{endpoint}'
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=body, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = min(2 ** attempt, 5)
                logger.warning(f'Notion API rate limited, waiting {wait}s (attempt {attempt + 1})')
                time.sleep(wait)
                continue
            if attempt < retries:
                time.sleep(1)
                continue
            raise NotionAPIError(f'Notion API {endpoint} returned {resp.status_code}')
        except requests.exceptions.Timeout:
            if attempt < retries:
                logger.warning(f'Notion API {endpoint} timeout (attempt {attempt + 1})')
                continue
            raise NotionAPIError(f'Notion API {endpoint} timed out after {retries + 1} attempts')
    raise NotionAPIError(f'Notion API {endpoint} failed after {retries + 1} attempts')


def _extract_record_map(data: dict) -> dict:
    """API 응답에서 recordMap 추출 (recordMapWithRoles 호환)"""
    return data.get('recordMap') or data.get('recordMapWithRoles') or {}


def _merge_record_maps(target: dict, source: dict):
    """두 recordMap을 병합한다."""
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(value, dict):
            target[key].update(value)


def _unwrap_nested_values(record_map: dict):
    """
    Notion 내부 API의 이중 중첩 value 구조를 평탄화하고 null 항목을 제거한다.
    { value: { value: {...}, role: "..." } } → { value: {...}, role: "..." }
    """
    for section_key in RECORD_MAP_SECTIONS:
        section = record_map.get(section_key, {})
        cleaned = {}
        for item_id, item in section.items():
            if not isinstance(item, dict):
                continue
            value = item.get('value')
            if value is None:
                continue
            if isinstance(value, dict) and 'value' in value and 'role' in value and isinstance(value['value'], dict):
                cleaned[item_id] = value
            else:
                cleaned[item_id] = item
        record_map[section_key] = cleaned


def _find_missing_block_ids(record_map: dict, scope_ids: set = None) -> set:
    """
    recordMap에서 참조되지만 존재하지 않는 블록 ID를 찾는다.
    scope_ids가 주어지면 해당 블록들의 content만 검사한다.
    """
    blocks = record_map.get('block', {})
    existing_ids = set(blocks.keys())
    referenced_ids = set()

    check_blocks = scope_ids if scope_ids else existing_ids
    for bid in check_blocks:
        block_data = blocks.get(bid)
        if not block_data:
            continue
        value = block_data.get('value', {})
        if not isinstance(value, dict):
            continue
        content = value.get('content', [])
        if isinstance(content, list):
            for child_id in content:
                if isinstance(child_id, str):
                    referenced_ids.add(child_id)

    return referenced_ids - existing_ids


def _fetch_blocks_by_ids(block_ids: list) -> dict:
    """syncRecordValues API로 특정 블록들을 가져온다."""
    data = _notion_post('syncRecordValues', {
        'requests': [
            {'pointer': {'table': 'block', 'id': bid}, 'version': -1}
            for bid in block_ids
        ]
    })

    block_data = _extract_record_map(data).get('block', {})

    results = {}
    for bid, bdata in block_data.items():
        if not isinstance(bdata, dict):
            continue
        if bdata.get('value') is None:
            continue
        results[bid] = bdata

    return results


def fetch_page(page_id: str) -> dict:
    """
    Notion 내부 API로 페이지 데이터를 가져온다.
    여러 chunk를 페이지네이션하고 누락된 블록(토글 자식 등)을 추가로 fetch한다.
    """
    uuid = _format_uuid(page_id)
    merged_record_map = {}

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

        record_map = _extract_record_map(data)
        _merge_record_maps(merged_record_map, record_map)

        next_cursor = data.get('cursor', {})
        stack = next_cursor.get('stack', [])
        if not stack:
            break

        cursor = next_cursor
        chunk_number += 1

        if chunk_number > MAX_CHUNKS:
            logger.warning(f'Notion page {page_id}: too many chunks, stopping at {chunk_number}')
            break

    _unwrap_nested_values(merged_record_map)

    # 누락된 블록(토글 자식 등) 추가 fetch
    fetched_ids = set()  # 이미 fetch 시도한 ID 추적 (무한 반복 방지)
    newly_added = None  # 증분 검색용

    for _ in range(MAX_MISSING_ROUNDS):
        missing_ids = _find_missing_block_ids(merged_record_map, newly_added) - fetched_ids
        if not missing_ids:
            break

        fetched_ids.update(missing_ids)
        newly_added = set()

        missing_list = list(missing_ids)
        for i in range(0, len(missing_list), BLOCK_BATCH_SIZE):
            batch = missing_list[i:i + BLOCK_BATCH_SIZE]
            fetched = _fetch_blocks_by_ids(batch)
            merged_record_map.setdefault('block', {}).update(fetched)
            newly_added.update(fetched.keys())

        # 새로 추가된 블록의 중첩 해제
        _unwrap_nested_values(merged_record_map)

    for key in RECORD_MAP_KEYS:
        merged_record_map.setdefault(key, {})

    merged_record_map.pop('space', None)

    return merged_record_map
