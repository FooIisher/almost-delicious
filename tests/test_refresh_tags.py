import unittest
from scripts.refresh_tags import recovery_state


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.r = {'id': '1', 'before': {'recipecategory': 'Breakfast', 'keywords': ['Easy']},
                  'after': {'recipecategory': ['breakfast'], 'keywords': ['easy']}}

    def doc(self, source):
        return {'_id': '1', 'found': True, '_source': source}

    def test_completed_skipped(self):
        self.assertEqual(recovery_state(self.r, self.doc(self.r['after'])), 'done')

    def test_original_can_resume_even_with_unrelated_changes(self):
        self.assertEqual(recovery_state(self.r, self.doc({**self.r['before'], 'name': 'New name'})), 'pending')

    def test_edits_partial_updates_and_missing_docs_are_conflicts(self):
        self.assertEqual(recovery_state(self.r, self.doc({'recipecategory': ['breakfast'], 'keywords': ['Easy']})), 'conflict')
        self.assertEqual(recovery_state(self.r, {'_id': '1', 'found': False}), 'conflict')
        self.assertEqual(recovery_state(self.r, self.doc({'recipecategory': 'Lunch', 'keywords': ['Easy']})), 'conflict')

    def test_absent_field_is_not_explicit_null(self):
        r = {'id': '1', 'before': {}, 'after': {'recipecategory': [], 'keywords': []}}
        self.assertEqual(recovery_state(r, self.doc({})), 'pending')
        self.assertEqual(recovery_state(r, self.doc({'keywords': None})), 'conflict')
