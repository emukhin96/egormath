"""Сверенные патчи не должны молча применяться к другой редакции OCR."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from .ege_repairs import repair_answers, repair_drafts


class EgeRepairTests(SimpleTestCase):
    def test_answer_patch_checks_both_sources_and_previous_value(self):
        spec = {'source_sha256': 'tex', 'pdf_sha256': 'pdf',
                'items': [{'id': '16.29', 'before': 'broken', 'answer_latex': 'correct'}]}
        with patch('pathlib.Path.exists', return_value=True), patch(
                'pathlib.Path.read_text', return_value=json.dumps(spec)):
            answers = {'16.29': 'broken'}
            self.assertEqual(repair_answers(answers, 'other', 'pdf'), [])
            self.assertEqual(answers['16.29'], 'broken')
            self.assertEqual(repair_answers(answers, 'tex', 'pdf'), ['16.29'])
            self.assertEqual(answers['16.29'], 'correct')
            with self.assertRaisesMessage(ValueError, '16.29'):
                repair_answers(answers, 'tex', 'pdf')

    def test_condition_patch_refuses_changed_image_binding(self):
        spec = {'source_sha256': 'tex', 'draft_patches': [
            {'id': '1.25', 'before': 'old', 'after': 'new', 'images': ['original'],
             'page': 13, 'verification': 'source'}]}
        task = SimpleNamespace(external_id='1.25', text_latex='old', images=['different'])
        with patch('pathlib.Path.read_text', return_value=json.dumps(spec)):
            with self.assertRaisesMessage(ValueError, '1.25'):
                repair_drafts([task], 'tex')
