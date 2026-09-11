"""Проверка восстановления самостоятельных задач из PDF-условий."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from .ostromogilsky_pdf_geometry import attach_pdf_geometry, geometry_body_from_pdf
from .textbook_parser import ImportBundle, TaskDraft


class PdfGeometryTests(SimpleTestCase):
    def test_accepts_entire_condition_and_preserves_printed_numbers(self):
        source = 'Сторона ромба равна 24, а один из углов этого ромба равен 150∘.\nНайдите высоту этого ромба.'
        result = geometry_body_from_pdf(source)
        self.assertIn('$24$', result)
        self.assertIn(r'$150^{\circ}$', result)
        self.assertIsNone(geometry_body_from_pdf(source + ' Другой вопрос.'))
        self.assertIsNone(geometry_body_from_pdf(source.replace('24', '2/4')))
        self.assertIsNone(geometry_body_from_pdf(source.replace('150', '−150')))

    def test_new_task_has_own_answer_image_metadata_and_exported_file(self):
        parent = TaskDraft(external_id='17.16.3', source_number='17.16.3',
                           source_path=['Геометрия'], collection_key='geo',
                           collection_title='Геометрия', topic_original='Четырёхугольники',
                           text_latex='Старое условие', images=['old'], tags=['DEMO'],
                           author_solution_latex='Чужое решение', review_status='approved')
        original = deepcopy(parent)
        bundle = ImportBundle(1, 'ostromogilsky', {}, [parent],
                              {'missing_task_ids':['17.16.4', '8.32'],
                               'answers_without_task':['17.16.4'], 'tasks_by_exam':{'17':1}})
        figures = {'17.16.4': {'body':'Сверенное условие.', 'image':b'png-data'}}
        with TemporaryDirectory() as directory:
            self.assertEqual(attach_pdf_geometry(bundle, figures, {'17.16.4':'$12$'}, directory), ['17.16.4'])
            new = bundle.tasks[1]
            self.assertEqual(new.text_latex, 'Сверенное условие.\n\\taskpic{1}')
            self.assertEqual(new.author_answer_latex, '$12$')
            self.assertEqual(new.exam_item_codes, ['OGE_2026_17'])
            self.assertEqual(new.images, ['oge-pdf-17-16-4'])
            self.assertEqual(new.tags, [])
            self.assertEqual(new.author_solution_latex, '')
            self.assertEqual(new.review_status, 'needs_review')
            self.assertEqual((Path(directory)/'oge-pdf-17-16-4.png').read_bytes(), b'png-data')
            self.assertEqual(bundle.diagnostics['missing_task_ids'], ['8.32'])
            self.assertEqual(bundle.diagnostics['tasks_by_exam']['17'], 2)
            self.assertEqual(parent, original)
            before = deepcopy(bundle.tasks)
            attach_pdf_geometry(bundle, figures, {'17.16.4':'$12$'}, directory)
            self.assertEqual(bundle.tasks, before)

    def test_missing_answer_or_reference_does_not_create_task(self):
        bundle = ImportBundle(1, 'ostromogilsky', {}, [], {})
        with TemporaryDirectory() as directory:
            result = attach_pdf_geometry(bundle, {'17.16.4':{'body':'Условие', 'image':b'png'}},
                                         {'17.16.4':'$12$'}, directory)
            self.assertEqual(result, [])
            self.assertEqual(bundle.tasks, [])
            self.assertEqual(list(Path(directory).iterdir()), [])
