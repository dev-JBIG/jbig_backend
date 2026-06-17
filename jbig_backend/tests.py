from django.test import SimpleTestCase

from .notion import _add_block_aliases, _cache_key, _find_missing_block_ids


class NotionRecordMapTests(SimpleTestCase):
    def test_find_missing_blocks_in_content_and_page_mentions(self):
        record_map = {
            'block': {
                'parent': {
                    'value': {
                        'id': 'parent',
                        'type': 'toggle',
                        'content': ['child-page', 'existing-page'],
                        'properties': {
                            'title': [
                                ['Course links ', [
                                    ['p', 'mentioned-page'],
                                    ['‣', ['p', 'external-mentioned-page']],
                                    ['‣', ['u', 'notion-user']],
                                    ['eoi', 'external-object'],
                                ]]
                            ]
                        },
                    }
                },
                'existing-page': {
                    'value': {
                        'id': 'existing-page',
                        'type': 'page',
                    }
                },
            }
        }

        self.assertEqual(
            _find_missing_block_ids(record_map),
            [
                'child-page',
                'mentioned-page',
                'external-mentioned-page',
                'external-object',
            ],
        )

    def test_block_aliases_support_hyphenated_and_compact_ids(self):
        compact = '123456781234123412341234567890ab'
        dashed = '12345678-1234-1234-1234-1234567890ab'
        block_data = {
            'value': {
                'id': dashed,
                'type': 'page',
            }
        }
        record_map = {'block': {dashed: block_data}}

        _add_block_aliases(record_map)

        self.assertIs(record_map['block'][compact], block_data)
        self.assertIs(record_map['block'][dashed], block_data)

    def test_cache_key_ignores_uuid_hyphens(self):
        self.assertEqual(
            _cache_key('12345678-1234-1234-1234-1234567890AB'),
            '123456781234123412341234567890ab',
        )
