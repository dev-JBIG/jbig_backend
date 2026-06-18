from django.test import SimpleTestCase

from .notion import _find_missing_block_ids, _merge_record_maps, _unwrap_nested_values


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

    def test_merge_does_not_downgrade_existing_block_value(self):
        record_map = {
            'block': {
                'child-page': {
                    'value': {
                        'id': 'child-page',
                        'type': 'page',
                    }
                },
            }
        }

        _merge_record_maps(record_map, {
            'block': {
                'child-page': {
                    'role': 'reader',
                }
            }
        })
        _unwrap_nested_values(record_map)

        self.assertIn('child-page', record_map['block'])
        self.assertEqual(record_map['block']['child-page']['value']['id'], 'child-page')

    def test_find_missing_blocks_when_child_record_has_no_value(self):
        record_map = {
            'block': {
                'parent': {
                    'value': {
                        'id': 'parent',
                        'type': 'toggle',
                        'content': ['child-page'],
                    }
                },
                'child-page': {
                    'role': 'reader',
                },
            }
        }

        self.assertEqual(
            _find_missing_block_ids(record_map),
            ['child-page'],
        )
