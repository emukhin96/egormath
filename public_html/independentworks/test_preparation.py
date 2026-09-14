"""Реальные сценарии подготовки состава и отмены выдачи."""
import tempfile
import io
from PIL import Image
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from problems.models import Source, Task, TaskSource, TaskImage, TaskSubitem, TaskBlock
from worksheets.models import Collection, Worksheet, WorksheetItem
from .models import Work, Position, Candidate, Asset
from .preparation import ziv_rows, from_worksheet, selection_fingerprint
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class PreparationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('prepare_owner')
        self.sheet = Worksheet.objects.create(owner=self.owner, title='Тема Зива')
        self.source = Source.objects.create(title='Зив')
        self.collection = Collection.objects.create(worksheet=self.sheet, source=self.source, is_published=True)

    def test_eight_variants_become_one_pair_of_two_positions(self):
        for variant in range(1, 9):
            for number in range(1, 3):
                task = Task.objects.create(text_latex=f'{variant}/{number}')
                TaskSource.objects.create(source=self.source, task=task, locator=f'sr/1/v{variant}/{number}')
                WorksheetItem.objects.create(worksheet=self.sheet, task=task, order=variant * 10 + number)
        rows = ziv_rows(self.collection, 3)
        work = from_worksheet(self.sheet, self.owner, 'Пара 3–4', rows)
        self.assertEqual(work.positions.count(), 2)
        self.assertEqual([p.candidates.count() for p in work.positions.all()], [2, 2])
        self.assertEqual({c.task.text_latex for p in work.positions.all() for c in p.candidates.all()}, {'3/1', '3/2', '4/1', '4/2'})
        self.assertTrue(selection_fingerprint(rows))

    def test_source_sheet_is_independent_and_missing_pair_is_visible(self):
        task = Task.objects.create(text_latex='Первый вариант')
        WorksheetItem.objects.create(worksheet=self.sheet, task=task)
        TaskSource.objects.create(source=self.source, task=task, locator='sr/1/v1/1')
        rows = ziv_rows(self.collection, 1)
        self.assertTrue(rows[0]['incomplete'])
        work = from_worksheet(self.sheet, self.owner, 'Работа', rows)
        self.sheet.items.all().delete()
        self.sheet.delete()
        work.refresh_from_db()
        self.assertIsNone(work.source_worksheet)
        self.assertEqual(work.positions.get().candidates.get().task, task)

    def test_no_mask_and_photos_disabled_is_rejected(self):
        work = Work.objects.create(owner=self.owner, title='Нет ввода')
        position = Position.objects.create(work=work)
        Candidate.objects.create(position=position, task=Task.objects.create(text_latex='Докажите'))
        with self.assertRaisesMessage(svc.WorkError, 'Нет способа ответить'):
            svc.prepare(work, self.owner, [self.owner.pk], allow_photos=False)

    def test_failed_issue_removes_copied_files(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            task = Task.objects.create(text_latex='С рисунком', answer_mask='{{number: 1}}')
            stream = io.BytesIO()
            Image.new('RGB', (10, 10)).save(stream, 'PNG')
            original = TaskImage.objects.create(task=task, image=ContentFile(stream.getvalue(), name='original.png'))
            work = Work.objects.create(owner=self.owner, title='Файлы')
            Candidate.objects.create(position=Position.objects.create(work=work), task=task)
            run = svc.prepare(work, self.owner, [self.owner.pk])
            with patch.object(Asset, 'save', side_effect=RuntimeError('Нет записи')):
                with self.assertRaises(RuntimeError):
                    svc.issue(run.pk)
            self.assertFalse(run.variants.exists())
            self.assertFalse(list(Path(directory).glob('independent_assets/**/*.*')))
            self.assertTrue(original.image.storage.exists(original.image.name))
