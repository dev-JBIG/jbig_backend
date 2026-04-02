"""
Notion 공식 API → react-notion-x ExtendedRecordMap 변환 모듈

공식 API 응답을 NotionRenderer가 이해하는 내부 포맷으로 변환한다.
"""
import logging
from datetime import datetime, timezone

from notion_client import Client
from django.conf import settings

logger = logging.getLogger(__name__)

BLOCK_TYPE_MAP = {
    'paragraph': 'text',
    'heading_1': 'header',
    'heading_2': 'sub_header',
    'heading_3': 'sub_sub_header',
    'bulleted_list_item': 'bulleted_list',
    'numbered_list_item': 'numbered_list',
    'to_do': 'to_do',
    'toggle': 'toggle',
    'code': 'code',
    'quote': 'quote',
    'callout': 'callout',
    'divider': 'divider',
    'image': 'image',
    'video': 'video',
    'file': 'file',
    'pdf': 'pdf',
    'bookmark': 'bookmark',
    'embed': 'embed',
    'equation': 'equation',
    'table': 'table',
    'table_row': 'table_row',
    'column_list': 'column_list',
    'column': 'column',
    'child_page': 'page',
    'child_database': 'collection_view_page',
    'synced_block': 'transclusion_container',
    'table_of_contents': 'table_of_contents',
    'breadcrumb': 'breadcrumb',
    'link_preview': 'bookmark',
    'audio': 'audio',
}


def _iso_to_ms(iso_str):
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _get_file_url(file_obj):
    if not file_obj:
        return None
    ft = file_obj.get('type', '')
    if ft == 'external':
        return file_obj.get('external', {}).get('url')
    if ft == 'file':
        return file_obj.get('file', {}).get('url')
    return None


def _apply_annotations(decorations, annotations):
    if annotations.get('bold'):
        decorations.append(['b'])
    if annotations.get('italic'):
        decorations.append(['i'])
    if annotations.get('strikethrough'):
        decorations.append(['s'])
    if annotations.get('underline'):
        decorations.append(['_'])
    if annotations.get('code'):
        decorations.append(['c'])
    color = annotations.get('color', 'default')
    if color != 'default':
        decorations.append(['h', color])


def convert_rich_text(rich_text_array):
    """공식 API rich_text → 내부 포맷 title 프로퍼티"""
    if not rich_text_array:
        return []

    result = []
    for item in rich_text_array:
        item_type = item.get('type', 'text')
        text = item.get('plain_text', '')
        decorations = []

        if item_type == 'equation':
            expression = item.get('equation', {}).get('expression', '')
            result.append(['⁍', [['e', expression]]])
            continue

        if item_type == 'mention':
            mention = item.get('mention', {})
            mt = mention.get('type', '')
            _apply_annotations(decorations, item.get('annotations', {}))
            if mt == 'page':
                decorations.append(['p', mention['page']['id']])
            elif mt == 'date':
                di = mention.get('date', {})
                decorations.append(['d', {
                    'type': 'date',
                    'start_date': di.get('start', ''),
                    'end_date': di.get('end'),
                }])
            result.append([text, decorations] if decorations else [text])
            continue

        _apply_annotations(decorations, item.get('annotations', {}))
        href = item.get('href')
        if href:
            decorations.append(['a', href])

        result.append([text, decorations] if decorations else [text])

    return result


def _convert_block(block, children_ids=None):
    """공식 API 블록 → 내부 포맷 블록"""
    block_id = block['id']
    block_type = block.get('type', '')
    internal_type = BLOCK_TYPE_MAP.get(block_type, 'text')

    parent = block.get('parent', {})
    pt = parent.get('type', '')
    parent_id = parent.get('page_id', '') if pt == 'page_id' else parent.get('block_id', '')

    value = {
        'id': block_id,
        'type': internal_type,
        'parent_id': parent_id,
        'parent_table': 'block',
        'alive': True,
        'created_time': _iso_to_ms(block.get('created_time')),
        'last_edited_time': _iso_to_ms(block.get('last_edited_time')),
    }

    if children_ids:
        value['content'] = children_ids

    td = block.get(block_type, {})

    # 텍스트 계열 블록
    if block_type in ('paragraph', 'heading_1', 'heading_2', 'heading_3',
                       'bulleted_list_item', 'numbered_list_item', 'quote', 'toggle'):
        title = convert_rich_text(td.get('rich_text', []))
        if title:
            value['properties'] = {'title': title}
        color = td.get('color', 'default')
        if color != 'default':
            value.setdefault('format', {})['block_color'] = color

    elif block_type == 'to_do':
        title = convert_rich_text(td.get('rich_text', []))
        value['properties'] = {}
        if title:
            value['properties']['title'] = title
        value['properties']['checked'] = [['Yes']] if td.get('checked') else [['No']]

    elif block_type == 'callout':
        title = convert_rich_text(td.get('rich_text', []))
        if title:
            value['properties'] = {'title': title}
        icon = td.get('icon')
        if icon:
            it = icon.get('type', '')
            if it == 'emoji':
                value.setdefault('format', {})['page_icon'] = icon['emoji']
            elif it == 'external':
                value.setdefault('format', {})['page_icon'] = icon['external']['url']
        color = td.get('color', 'default')
        if color != 'default':
            value.setdefault('format', {})['block_color'] = color

    elif block_type == 'code':
        title = convert_rich_text(td.get('rich_text', []))
        value['properties'] = {}
        if title:
            value['properties']['title'] = title
        value['properties']['language'] = [[td.get('language', 'Plain Text')]]
        caption = td.get('caption', [])
        if caption:
            value['properties']['caption'] = convert_rich_text(caption)

    elif block_type == 'image':
        url = _get_file_url(td)
        if url:
            value['properties'] = {'source': [[url]]}
            value['format'] = {'display_source': url, 'block_width': 680}
        caption = td.get('caption', [])
        if caption:
            value.setdefault('properties', {})['caption'] = convert_rich_text(caption)

    elif block_type == 'video':
        url = _get_file_url(td)
        if url:
            value['properties'] = {'source': [[url]]}
            value['format'] = {'display_source': url, 'block_width': 680}

    elif block_type in ('file', 'pdf', 'audio'):
        url = _get_file_url(td)
        if url:
            value['properties'] = {'source': [[url]]}
            value['format'] = {'display_source': url}

    elif block_type == 'bookmark':
        url = td.get('url', '')
        value['properties'] = {'link': [[url]]}
        caption = td.get('caption', [])
        if caption:
            value['properties']['title'] = convert_rich_text(caption)

    elif block_type == 'link_preview':
        value['properties'] = {'link': [[td.get('url', '')]]}

    elif block_type == 'embed':
        url = td.get('url', '')
        value['properties'] = {'source': [[url]]}
        value['format'] = {'display_source': url, 'block_width': 680}

    elif block_type == 'equation':
        value['properties'] = {'title': [['⁍', [['e', td.get('expression', '')]]]]}

    elif block_type == 'table':
        tw = td.get('table_width', 0)
        value['format'] = {
            'table_block_column_order': [f'col_{i}' for i in range(tw)],
            'table_block_column_header': td.get('has_column_header', False),
            'table_block_row_header': td.get('has_row_header', False),
        }

    elif block_type == 'table_row':
        cells = td.get('cells', [])
        props = {}
        for i, cell in enumerate(cells):
            title = convert_rich_text(cell)
            if title:
                props[f'col_{i}'] = title
        if props:
            value['properties'] = props

    elif block_type == 'child_page':
        value['properties'] = {'title': [[td.get('title', '')]]}

    elif block_type == 'synced_block':
        sf = td.get('synced_from')
        if sf:
            value['type'] = 'transclusion_reference'
            value.setdefault('format', {})['transclusion_reference_pointer'] = {
                'id': sf.get('block_id', ''),
                'table': 'block',
            }

    elif block_type == 'table_of_contents':
        color = td.get('color', 'default')
        if color != 'default':
            value.setdefault('format', {})['block_color'] = color

    return block_id, value


def _convert_page(page, top_level_ids):
    """공식 API 페이지 → 내부 포맷 페이지 블록"""
    page_id = page['id']

    title_text = ''
    for prop in page.get('properties', {}).values():
        if prop.get('type') == 'title':
            title_text = ''.join(i.get('plain_text', '') for i in prop.get('title', []))
            break

    value = {
        'id': page_id,
        'type': 'page',
        'properties': {'title': [[title_text]]},
        'content': top_level_ids,
        'parent_table': 'space',
        'alive': True,
        'created_time': _iso_to_ms(page.get('created_time')),
        'last_edited_time': _iso_to_ms(page.get('last_edited_time')),
    }

    fmt = {}
    icon = page.get('icon')
    if icon:
        it = icon.get('type', '')
        if it == 'emoji':
            fmt['page_icon'] = icon['emoji']
        elif it == 'external':
            fmt['page_icon'] = icon['external']['url']
        elif it == 'file':
            fmt['page_icon'] = icon['file']['url']

    cover = page.get('cover')
    if cover:
        cover_url = _get_file_url(cover)
        if cover_url:
            fmt['page_cover'] = cover_url

    if fmt:
        value['format'] = fmt

    return page_id, value


def _fetch_children(notion, block_id):
    """한 블록의 직계 자식만 가져온다 (재귀 없음)."""
    children = []
    cursor = None
    while True:
        kwargs = {'block_id': block_id, 'page_size': 100}
        if cursor:
            kwargs['start_cursor'] = cursor
        response = notion.blocks.children.list(**kwargs)
        children.extend(response.get('results', []))
        if not response.get('has_more'):
            break
        cursor = response.get('next_cursor')
    return children


def _fetch_blocks_bfs(notion, page_id, max_depth=3):
    """
    BFS로 블록을 가져온다. max_depth로 깊이를 제한하여 API 호출 수를 통제한다.
    depth 0 = 페이지 직계 자식, depth 1 = 그 자식들, ...
    """
    all_blocks = []
    queue = [(page_id, 0)]

    while queue:
        parent_id, depth = queue.pop(0)
        children = _fetch_children(notion, parent_id)
        all_blocks.extend(children)

        if depth < max_depth:
            for block in children:
                if block.get('has_children'):
                    queue.append((block['id'], depth + 1))

    return all_blocks


def fetch_page(page_id: str) -> dict:
    """
    공식 Notion API로 페이지를 가져와 ExtendedRecordMap 포맷으로 반환한다.
    깊이를 제한하여 대형 페이지에서도 timeout 없이 동작한다.
    """
    notion = Client(auth=settings.NOTION_API_KEY)

    page = notion.pages.retrieve(page_id)
    all_blocks = _fetch_blocks_bfs(notion, page_id, max_depth=3)

    # 부모-자식 매핑
    parent_children = {}
    for block in all_blocks:
        parent = block.get('parent', {})
        pt = parent.get('type', '')
        pid = parent.get('block_id', page_id) if pt == 'block_id' else page_id
        parent_children.setdefault(pid, []).append(block['id'])

    block_map = {}

    # 페이지 블록
    top_ids = parent_children.get(page_id, [])
    pid, pval = _convert_page(page, top_ids)
    block_map[pid] = {'value': pval, 'role': 'reader'}

    # 하위 블록
    for block in all_blocks:
        children_ids = parent_children.get(block['id'])
        bid, bval = _convert_block(block, children_ids)
        block_map[bid] = {'value': bval, 'role': 'reader'}

    return {
        'block': block_map,
        'collection': {},
        'collection_view': {},
        'notion_user': {},
        'collection_query': {},
        'signed_urls': {},
    }
