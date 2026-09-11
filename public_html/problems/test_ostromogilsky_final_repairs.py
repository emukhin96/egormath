"""Защита сверенных исправлений и полнота переносимого пакета рисунков."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase
from .ostromogilsky_final_repairs import apply_final_repairs, copy_referenced_images


class FinalRepairsTests(SimpleTestCase):
    def test_nested_answer_math_does_not_break_pairs(self):
        from .ostromogilsky_parser import normalize_oge_answer
        for source, expected in [
                (r'$( $$7 ; 7+\sqrt{11}$$ )$', r'$( 7 ; 7+\sqrt{11} )$'),
                (r'$2; $$\displaystyle \frac{13}{4}$', r'$2; \displaystyle \frac{13}{4}$')]:
            self.assertEqual(normalize_oge_answer(source), expected)
            self.assertEqual(normalize_oge_answer(expected), expected)

    def test_unknown_source_and_changed_draft_are_preserved(self):
        row = {'id': '8.1', 'source': 'Условие. Ответ:', 'before': 'OCR', 'before_images': [],
               'latex': 'Условие.', 'images': []}
        page = MagicMock()
        page.get_text.return_value = 'Задача 8.1. Условие. Ответ:'
        doc = MagicMock()
        doc.__enter__.return_value = doc
        doc.resolve_names.return_value = {'task::8.1': {'page': 0}}
        doc.__getitem__.return_value = page
        def run(body='OCR'):
            task = SimpleNamespace(external_id='8.1', text_latex=body, images=[], warnings=[],
                                   subitems=[], author_answer_latex='$7$', status='needs_review')
            bundle = SimpleNamespace(tasks=[task], diagnostics={})
            with patch('pathlib.Path.read_text', return_value=json.dumps([row])), patch('pymupdf.open', return_value=doc):
                apply_final_repairs(bundle, 'source.pdf', '/tmp/unused')
            return task
        changed = run('Редактор уже исправил')
        self.assertEqual(changed.text_latex, 'Редактор уже исправил')
        result = run()
        self.assertEqual(result.text_latex, 'Условие.')
        self.assertEqual(result.author_answer_latex, '$7$')
        self.assertEqual(result.status, 'needs_review')
        page.get_text.return_value = 'Задача 8.1. Другое условие. Ответ:'
        self.assertEqual(run().text_latex, 'OCR')

    def test_package_requires_every_image_and_keeps_restored_one(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source'; dest = root/'out'
            source.mkdir(); dest.mkdir()
            (source/'a.png').write_bytes(b'original'); (dest/'a.png').write_bytes(b'restored')
            (source/'b.jpg').write_bytes(b'second')
            bundle = SimpleNamespace(tasks=[SimpleNamespace(images=['a', 'b'])], diagnostics={})
            copy_referenced_images(bundle, source, dest)
            self.assertEqual((dest/'a.png').read_bytes(), b'restored')
            self.assertEqual((dest/'b.jpg').read_bytes(), b'second')
            bundle.tasks[0].images.append('missing')
            with self.assertRaisesRegex(ValueError, 'missing'):
                copy_referenced_images(bundle, source, dest)
