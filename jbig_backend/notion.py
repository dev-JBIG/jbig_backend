"""
Notion 내부 API 프록시 — splitbee 대체 셀프 호스팅

Notion의 내부 API(loadPageChunk, syncRecordValues)를 호출하여
react-notion-x가 그대로 소비할 수 있는 ExtendedRecordMap 포맷을 반환한다.
공개 페이지만 접근 가능하며 API 키가 필요하지 않다.
"""
import re
import requests
import logging

logger = logging.getLogger(__name__)

NOTION_API = 'https://www.notion.so/api/v3'
HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0',
}


def _format_uuid(page_id: str) -> str:
    """하이픈 없는 32자 hex를 UUID 포맷(8-4-4-4-12)으로 변환"""
    clean = re.sub(r'[^a-fA-F0-9]', '', page_id)
    if len(clean) != 32:
        return page_id
    return f'{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}'


def _merge_record_maps(target: dict, source: dict):
    """두 recordMap을 병합한다."""
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(value, dict):
            target[key].update(value)


def _unwrap_nested_values(record_map: dict):
    """
    Notion 내부 API는 { value: { value: {...}, role: "..." } } 형태로 중첩 반환.
    react-notion-x는 { value: {...}, role: "..." } 형태를 기대하므로 풀어준다.
    """
    for section_key in ('block', 'collection', 'collection_view', 'notion_user'):
        section = record_map.get(section_key, {})
        for item_id, item in section.items():
            if isinstance(item, dict) and 'value' in item and isinstance(item['value'], dict):
                inner = item['value']
                if 'value' in inner and 'role' in inner and isinstance(inner['value'], dict):
                    section[item_id] = inner


def _find_missing_block_ids(record_map: dict) -> set:
    """recordMap에서 참조되지만 존재하지 않는 블록 ID를 찾는다."""
    blocks = record_map.get('block', {})
    existing_ids = set(blocks.keys())
    referenced_ids = set()

    for block_data in blocks.values():
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
    resp = requests.post(
        f'{NOTION_API}/syncRecordValues',
        json={
            'requests': [
                {'pointer': {'table': 'block', 'id': bid}, 'version': -1}
                for bid in block_ids
            ]
        },
        headers=HEADERS,
        timeout=15,
    )

    if resp.status_code != 200:
        logger.warning(f'syncRecordValues returned {resp.status_code}')
        return {}

    data = resp.json()
    results = {}
    for record in data.get('recordMap', {}).get('block', {}).items():
        results[record[0]] = record[1]

    return results


def fetch_page(page_id: str) -> dict:
    """
    Notion 내부 API로 페이지 데이터를 가져온다.
    여러 chunk를 페이지네이션하고 누락된 블록(토글 자식 등)을 추가로 fetch한다.
    """
    uuid = _format_uuid(page_id)
    merged_record_map = {}

    # 1단계: loadPageChunk로 페이지 데이터 가져오기
    chunk_number = 0
    cursor = {'stack': []}

    while True:
        resp = requests.post(
            f'{NOTION_API}/loadPageChunk',
            json={
                'page': {'id': uuid},
                'limit': 100,
                'cursor': cursor,
                'chunkNumber': chunk_number,
                'verticalColumns': False,
            },
            headers=HEADERS,
            timeout=15,
        )

        if resp.status_code != 200:
            raise Exception(f'Notion API returned {resp.status_code}')

        data = resp.json()
        record_map = data.get('recordMap', {})
        _merge_record_maps(merged_record_map, record_map)

        next_cursor = data.get('cursor', {})
        stack = next_cursor.get('stack', [])
        if not stack:
            break

        cursor = next_cursor
        chunk_number += 1

        if chunk_number > 50:
            logger.warning(f'Notion page {page_id}: too many chunks, stopping at {chunk_number}')
            break

    # 중첩 구조 해제
    _unwrap_nested_values(merged_record_map)

    # 2단계: 누락된 블록(토글 자식 등) 추가 fetch
    for _ in range(10):  # 최대 10회 반복 (깊은 중첩 대응)
        missing_ids = _find_missing_block_ids(merged_record_map)
        if not missing_ids:
            break

        # 한 번에 최대 100개씩 요청
        missing_list = list(missing_ids)
        for i in range(0, len(missing_list), 100):
            batch = missing_list[i:i + 100]
            fetched = _fetch_blocks_by_ids(batch)

            # 가져온 블록도 중첩 해제
            for bid, bdata in fetched.items():
                if isinstance(bdata, dict) and 'value' in bdata and isinstance(bdata['value'], dict):
                    inner = bdata['value']
                    if 'value' in inner and 'role' in inner and isinstance(inner['value'], dict):
                        fetched[bid] = inner

            merged_record_map.setdefault('block', {}).update(fetched)

    # react-notion-x가 기대하는 키 보장
    for key in ('block', 'collection', 'collection_view', 'notion_user', 'collection_query', 'signed_urls'):
        merged_record_map.setdefault(key, {})

    # space 등 불필요한 키 제거 (프론트에서 안 씀)
    merged_record_map.pop('space', None)

    return merged_record_map
