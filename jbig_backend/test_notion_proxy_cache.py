from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import notion


PAGE_ID = '3021859be145800e9e88e93bc146b840'
DASHED_PAGE_ID = '3021859b-e145-800e-9e88-e93bc146b840'


def block_record(block_id, content=None):
    value = {'id': block_id, 'type': 'toggle'}
    if content is not None:
        value['content'] = content
    return {'value': value}


def missing_block_count(record_map):
    blocks = record_map.get('block', {})
    missing = 0
    for block in blocks.values():
        if not isinstance(block, dict):
            continue
        value = block.get('value')
        if not isinstance(value, dict):
            continue
        for child_id in value.get('content') or []:
            child = blocks.get(child_id)
            if not isinstance(child, dict) or not child.get('value'):
                missing += 1
    return missing


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


class NotionProxyCacheReproductionTests(TestCase):
    def setUp(self):
        notion._cache.clear()
        notion._build_locks.clear()
        self.original_notion_post = notion._notion_post
        self.original_thread = notion.threading.Thread
        self.original_sleep = notion._time.sleep
        self.original_max_incomplete_build_retries = notion.MAX_INCOMPLETE_BUILD_RETRIES
        notion._time.sleep = lambda seconds: None

        user = get_user_model().objects.create_user(
            email='notion-test@example.com',
            username='notion-test',
            password='pw',
            is_active=True,
            is_verified=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def tearDown(self):
        notion._notion_post = self.original_notion_post
        notion.threading.Thread = self.original_thread
        notion._time.sleep = self.original_sleep
        notion.MAX_INCOMPLETE_BUILD_RETRIES = self.original_max_incomplete_build_retries
        notion._cache.clear()
        notion._build_locks.clear()

    def test_expired_cache_refresh_keeps_complete_cache_when_refresh_is_partial(self):
        def complete_map():
            return {
                'block': {
                    'root': block_record('root', ['a', 'b', 'c']),
                    'a': block_record('a'),
                    'b': block_record('b'),
                    'c': block_record('c'),
                }
            }

        def partial_map():
            return {
                'block': {
                    'root': block_record('root', ['a', 'b', 'c']),
                    'a': block_record('a'),
                }
            }

        load_page_responses = [complete_map()] + [
            partial_map()
            for _ in range(notion.MAX_INCOMPLETE_BUILD_RETRIES + 1)
        ]

        def fake_notion_post(endpoint, body, retries=2):
            if endpoint == 'loadPageChunk':
                return {
                    'recordMap': load_page_responses.pop(0),
                    'cursor': {'stack': []},
                }
            if endpoint == 'syncRecordValues':
                return {'recordMap': {'block': {}}}
            raise AssertionError(f'unexpected endpoint: {endpoint}')

        notion._notion_post = fake_notion_post
        notion.threading.Thread = ImmediateThread

        first = self.client.get(f'/api/notion/{PAGE_ID}/')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.json()['block']), 4)
        self.assertEqual(missing_block_count(first.json()), 0)

        notion._cache[PAGE_ID]['expires'] = 0

        with self.assertLogs('jbig_backend.notion', level='WARNING') as logs:
            stale = self.client.get(f'/api/notion/{PAGE_ID}/')
        self.assertEqual(stale.status_code, 200)
        self.assertEqual(len(stale.json()['block']), 4)
        self.assertEqual(missing_block_count(stale.json()), 0)
        self.assertTrue(
            any('Notion cache refresh rejected' in message for message in logs.output)
        )

        refreshed = self.client.get(f'/api/notion/{PAGE_ID}/')
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(len(refreshed.json()['block']), 4)
        self.assertEqual(missing_block_count(refreshed.json()), 0)

    def test_initial_load_retries_incomplete_record_map_before_caching(self):
        notion.MAX_INCOMPLETE_BUILD_RETRIES = 1

        partial = {
            'block': {
                'root': block_record('root', ['a', 'b']),
                'a': block_record('a'),
            }
        }
        complete = {
            'block': {
                'root': block_record('root', ['a', 'b']),
                'a': block_record('a'),
                'b': block_record('b'),
            }
        }
        load_page_responses = [partial, complete]
        load_page_calls = []

        def fake_notion_post(endpoint, body, retries=2):
            if endpoint == 'loadPageChunk':
                load_page_calls.append(body['page']['id'])
                return {
                    'recordMap': load_page_responses.pop(0),
                    'cursor': {'stack': []},
                }
            if endpoint == 'syncRecordValues':
                return {'recordMap': {'block': {}}}
            raise AssertionError(f'unexpected endpoint: {endpoint}')

        notion._notion_post = fake_notion_post

        response = self.client.get(f'/api/notion/{PAGE_ID}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(load_page_calls), 2)
        self.assertEqual(len(response.json()['block']), 3)
        self.assertEqual(missing_block_count(response.json()), 0)
        self.assertEqual(notion._cache[PAGE_ID]['missing_count'], 0)

    def test_initial_load_prunes_unresolved_children_after_bounded_retries(self):
        def partial_map():
            return {
                'block': {
                    'root': block_record('root', ['a', 'b']),
                    'a': block_record('a'),
                }
            }

        load_page_calls = []

        def fake_notion_post(endpoint, body, retries=2):
            if endpoint == 'loadPageChunk':
                load_page_calls.append(body['page']['id'])
                return {
                    'recordMap': partial_map(),
                    'cursor': {'stack': []},
                }
            if endpoint == 'syncRecordValues':
                return {'recordMap': {'block': {}}}
            raise AssertionError(f'unexpected endpoint: {endpoint}')

        notion._notion_post = fake_notion_post

        response = self.client.get(f'/api/notion/{PAGE_ID}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(load_page_calls), notion.MAX_INCOMPLETE_BUILD_RETRIES + 1)
        self.assertEqual(response.json()['block']['root']['value']['content'], ['a'])
        self.assertEqual(missing_block_count(response.json()), 0)
        self.assertEqual(notion._cache[PAGE_ID]['missing_count'], 1)
        self.assertLessEqual(
            notion._cache[PAGE_ID]['expires'] - notion._time.time(),
            notion.INCOMPLETE_CACHE_TTL + 1,
        )

    def test_hyphenated_and_plain_page_ids_share_one_cache_entry(self):
        load_page_calls = []

        def fake_notion_post(endpoint, body, retries=2):
            if endpoint == 'loadPageChunk':
                load_page_calls.append(body['page']['id'])
                return {
                    'recordMap': {'block': {'root': block_record('root')}},
                    'cursor': {'stack': []},
                }
            raise AssertionError(f'unexpected endpoint: {endpoint}')

        notion._notion_post = fake_notion_post

        plain = self.client.get(f'/api/notion/{PAGE_ID}/')
        dashed = self.client.get(f'/api/notion/{DASHED_PAGE_ID}/')

        self.assertEqual(plain.status_code, 200)
        self.assertEqual(dashed.status_code, 200)
        self.assertEqual(len(load_page_calls), 1)
        self.assertEqual(set(notion._cache.keys()), {PAGE_ID})

    def test_build_returns_successfully_after_max_missing_rounds_even_with_unresolved_child(self):
        child_chain = {
            f'b{i}': block_record(f'b{i}', [f'b{i + 1}'])
            for i in range(1, 6)
        }
        child_chain['b6'] = block_record('b6')

        def fake_notion_post(endpoint, body, retries=2):
            if endpoint == 'loadPageChunk':
                return {
                    'recordMap': {'block': {'root': block_record('root', ['b1'])}},
                    'cursor': {'stack': []},
                }
            if endpoint == 'syncRecordValues':
                requested_ids = [
                    request['pointer']['id']
                    for request in body['requests']
                ]
                return {
                    'recordMap': {
                        'block': {
                            block_id: child_chain[block_id]
                            for block_id in requested_ids
                            if block_id in child_chain
                        }
                    }
                }
            raise AssertionError(f'unexpected endpoint: {endpoint}')

        notion._notion_post = fake_notion_post

        response = self.client.get(f'/api/notion/{PAGE_ID}/')

        self.assertEqual(response.status_code, 200)
        record_map = response.json()
        self.assertEqual(len(record_map['block']), 7)
        self.assertEqual(missing_block_count(record_map), 0)
