"""Восстановление систем должно сохранять знаки, границы и номера вариантов."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .ostromogilsky_pdf_inequalities import system_body_from_pdf, attach_pdf_systems
from .textbook_parser import ImportBundle, TaskDraft


class PdfSystemTests(SimpleTestCase):
    source = '''Прототип
Ответ
Укажите решение системы неравенств
{︃
𝑥 + 4 ≥ −3,4,
𝑥 + 5 ≤ 0.
1) [−7,4; −5];
2) [−5; +∞);
3) (−∞; −7,4];
4) (−∞; −7,4] ∪ [−5; +∞).
'''

    def test_preserves_both_relations_and_all_interval_endpoints(self):
        body = system_body_from_pdf(self.source)
        self.assertIn(r'x+4\geq -3{,}4,\\x+5\leq 0.', body)
        self.assertIn(r'1) $[-7{,}4;-5]$', body)
        self.assertIn(r'4) $(-\infty;-7{,}4]\cup[-5;+\infty)$', body)
        self.assertEqual(body.count(') $'), 4)

    def test_incomplete_or_unrecognized_content_is_not_accepted(self):
        for source in [self.source.replace('3)', '2)'), self.source.replace('≤', '='),
                       self.source.replace('𝑥 + 5 ≤ 0.',''), self.source + 'Примечание',
                       self.source.replace('[−5; +∞)', '[−5 +∞)'),
                       self.source.replace('𝑥 + 4', '𝑥 / 4')]:
            with self.subTest(source=source):
                self.assertIsNone(system_body_from_pdf(source))

    def test_graphical_options_require_four_numbered_choices(self):
        source = self.source[:self.source.index('1)')] + '1) x; 2) x; 3) x; 4) x.'
        self.assertTrue(system_body_from_pdf(source, True).endswith(r'\taskpic{1}'))
        self.assertIsNone(system_body_from_pdf(source.replace('4)', '3)'), True))

    def test_export_does_not_inherit_parent_image_or_approval(self):
        parent = TaskDraft(external_id='13.3.13',source_number='13.3.13',source_path=['Системы'],
                           collection_key='systems',collection_title='Системы',topic_original='Неравенства',
                           text_latex='Старое условие',images=['wrong-image'],tags=['DEMO'],
                           review_status='approved',author_solution_latex='Чужое решение')
        original = deepcopy(parent)
        bundle = ImportBundle(1,'ostromogilsky',{},[parent],{'missing_task_ids':['13.3.14']})
        systems = {'13.3.14':{'body':system_body_from_pdf(self.source),'image':None}}
        with TemporaryDirectory() as directory:
            attach_pdf_systems(bundle,systems,{'13.3.14':'$1$'},directory)
            draft = bundle.tasks[1]
            self.assertEqual(draft.images,[])
            self.assertEqual(draft.author_answer_latex,'$1$')
            self.assertEqual(draft.exam_item_codes,['OGE_2026_13'])
            self.assertEqual(draft.tags,[])
            self.assertEqual(draft.author_solution_latex,'')
            self.assertEqual(draft.review_status,'needs_review')
            self.assertEqual(bundle.diagnostics['missing_task_ids'],[])
            self.assertEqual(list(Path(directory).iterdir()),[])
            before=deepcopy(bundle.tasks)
            attach_pdf_systems(bundle,systems,{'13.3.14':'$1$'},directory)
            self.assertEqual(bundle.tasks,before)
            self.assertEqual(parent,original)
