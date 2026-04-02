"""
Notion 내부 API 프록시 — splitbee 대체 셀프 호스팅

Notion의 내부 API(loadPageChunk)를 호출하여 react-notion-x가
그대로 소비할 수 있는 ExtendedRecordMap 포맷을 반환한다.
공개 페이지만 접근 가능하며 API 키가 필요하지 않다.
"""
import re
import requests
import logging

logger = logging.getLogger(__name__)

NOTION_API = 'https://www.notion.so/api/v3'


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


def fetch_page(page_id: str) -> dict:
    """
    Notion 내부 API로 페이지 데이터를 가져온다.
    여러 chunk를 페이지네이션하여 전체 recordMap을 반환한다.
    """
    uuid = _format_uuid(page_id)
    merged_record_map = {}

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
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0',
            },
            timeout=15,
        )

        if resp.status_code != 200:
            raise Exception(f'Notion API returned {resp.status_code}')

        data = resp.json()
        record_map = data.get('recordMap', {})
        _merge_record_maps(merged_record_map, record_map)

        # 다음 chunk 확인
        next_cursor = data.get('cursor', {})
        stack = next_cursor.get('stack', [])
        if not stack:
            break

        cursor = next_cursor
        chunk_number += 1

        if chunk_number > 50:
            logger.warning(f'Notion page {page_id}: too many chunks, stopping at {chunk_number}')
            break

    # react-notion-x가 기대하는 키 보장
    for key in ('block', 'collection', 'collection_view', 'notion_user', 'collection_query', 'signed_urls'):
        merged_record_map.setdefault(key, {})

    # space 등 불필요한 키 제거 (프론트에서 안 씀)
    merged_record_map.pop('space', None)

    return merged_record_map
