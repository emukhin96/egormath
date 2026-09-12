import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase

from problems.models import (ExamItem, ExamModel, Task, TextbookImportBatch,
                             TextbookTaskDraft)


class LoadEgeDraftsCommandTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        user_model = get_user_model()
        user_model.objects.create_superuser(
            username='egor', email='egor@example.test', password='secret')
        model = ExamModel.objects.get(
            code='EXAM_EGE_PROFILE_2027')
        ExamItem.objects.get_or_create(
            code='EGE_PROFILE_2027_01', defaults={
                'exam_model': model, 'item_number': 1,
                'name': 'Задание 1', 'order': 1})

    def bundle(self, *, text='Условие задачи.', source_sha='source-v1'):
        payload = {
            'schema_version': 1,
            'profile': 'ostromogilsky_ege',
            'source': {
                'tasks_sha256': source_sha,
                'answers_file': 'answers.pdf',
            },
            'tasks': [{
                'external_id': '1.1.01',
                'source_number': '1',
                'text_latex': text,
                'author_answer_latex': '2',
                'exam_item_codes': ['EGE_PROFILE_2027_01'],
            }],
        }
        directory = Path(self.tempdir.name)
        path = directory / 'bundle.json'
        path.write_text(json.dumps(payload, ensure_ascii=False))
        return path, payload

    def tearDown(self):
        self.tempdir.cleanup()

    def test_dryrun_validates_without_creating_any_records(self):
        path, _ = self.bundle()
        output = StringIO()

        call_command('load_ege_drafts', path, stdout=output)

        self.assertIn('записей не создано', output.getvalue())
        self.assertEqual(TextbookImportBatch.objects.count(), 0)
        self.assertEqual(TextbookTaskDraft.objects.count(), 0)
        self.assertEqual(Task.objects.count(), 0)

    def test_repeated_exact_commit_preserves_edited_draft_and_creates_no_task(self):
        path, _ = self.bundle()
        call_command('load_ege_drafts', path, '--commit')
        draft = TextbookTaskDraft.objects.get(external_id='1.1.01')
        draft.text_latex = 'Ручная правка редактора.'
        draft.save(update_fields=['text_latex'])

        output = StringIO()
        call_command('load_ege_drafts', path, '--commit', stdout=output)

        self.assertIn('unchanged:', output.getvalue())
        self.assertEqual(TextbookImportBatch.objects.count(), 1)
        self.assertEqual(TextbookTaskDraft.objects.count(), 1)
        self.assertEqual(
            TextbookTaskDraft.objects.get(pk=draft.pk).text_latex,
            'Ручная правка редактора.')
        self.assertEqual(Task.objects.count(), 0)

    def test_changed_bundle_with_same_source_sha_is_rejected(self):
        path, _ = self.bundle()
        call_command('load_ege_drafts', path, '--commit')
        changed_path, _ = self.bundle(text='Изменённое условие.', source_sha='source-v1')

        with self.assertRaisesRegex(CommandError, 'уже есть другая версия'):
            call_command('load_ege_drafts', changed_path, '--commit')

        self.assertEqual(TextbookImportBatch.objects.count(), 1)
        self.assertEqual(TextbookTaskDraft.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 0)
