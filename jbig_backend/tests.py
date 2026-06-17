from django.test import SimpleTestCase

from .notion import _find_missing_block_ids


class NotionRecordMapTests(SimpleTestCase):
    def test_find_missing_blocks_in_content(self):
        record_map = {
            'block': {
                'parent': {
                    'value': {
                        'id': 'parent',
                        'type': 'toggle',
                        'content': ['child-page', 'existing-page'],
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
            ['child-page'],
        )
