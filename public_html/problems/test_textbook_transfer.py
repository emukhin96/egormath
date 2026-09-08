import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase

from problems.models import (Source, TextbookImportAsset, TextbookImportBatch,
                             TextbookTaskDraft, Topic)
from problems.rubricator import seed_rubricator
from problems.test_textbook_import import TINY_PNG
from problems.tests import make_teacher
from problems.textbook_transfer import (export_batches, import_batches,
                                        latest_batches)


class TextbookTransferTests(TestCase):
    def setUp(self):
        seed_rubricator()
        self.teacher = make_teacher()
        self.admin = User.objects.create_superuser(
            'prodadmin', 'admin@example.com', 'pass12345')
        self.topic = Topic.objects.get(code='ARI.04.04')
        self.source = Source.objects.create(
            title='Зив, дидактические материалы', author='Зив', year=2014)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name) / 'media'
        self.media.mkdir()

    def _make_batch(self, *, profile, title, created_by=None, status='review'):
        batch = TextbookImportBatch.objects.create(
            title=title, profile=profile, source=self.source,
            created_by=created_by or self.teacher, status=status,
            diagnostics={'pages': 2})
        TextbookTaskDraft.objects.create(
            batch=batch,
            external_id=f'{profile}-1.1',
            source_number='1.1',
            source_path=['Тема'],
            collection_key='t1',
            collection_title='Тема',
            topic_original='Проценты',
            topic=self.topic,
            topic_ids=[self.topic.pk],
            text_latex='Найдите $10\\%$.',
            subitems=[],
            images=['рис1.png'],
            topic_candidates=[{
                'id': self.topic.pk, 'code': self.topic.code,
                'name': str(self.topic), 'score': 1, 'reason': 'exact-name',
            }],
            author_answer_latex='20',
            status=TextbookTaskDraft.STATUS_APPROVED,
            confidence=Decimal('1.000'),
        )
        return batch

    def test_latest_batches_one_per_profile(self):
        self._make_batch(profile='ziv', title='Зив старый')
        newest = self._make_batch(profile='ziv', title='Зив новый')
        shestakov = self._make_batch(profile='shestakov', title='Шестаков')
        self._make_batch(profile='galitsky', title='Галицкий')
        chosen = latest_batches(('ziv', 'shestakov'))
        self.assertEqual([b.pk for b in chosen], [newest.pk, shestakov.pk])

    def test_export_import_remaps_topics_and_owner(self):
        with self.settings(MEDIA_ROOT=str(self.media)):
            batch = self._make_batch(
                profile='ziv', title='Зив сверка', status='ready')
            TextbookImportAsset.objects.create(
                batch=batch, stem='рис1', original_name='рис1.png',
                file=ContentFile(TINY_PNG, name='рис1.png'))
            dest = Path(self.tmp.name) / 'dump'
            export_batches(dest, profiles=('ziv',))
            self.assertTrue((dest / 'batches.json').is_file())
            self.assertTrue(list((dest / 'assets').rglob('*.png')))

            TextbookImportAsset.objects.all().delete()
            TextbookTaskDraft.objects.all().delete()
            TextbookImportBatch.objects.all().delete()

            created = import_batches(dest, username='prodadmin')
            self.assertEqual(len(created), 1)
            imported = created[0]
            self.assertEqual(imported.created_by, self.admin)
            self.assertEqual(imported.profile, 'ziv')
            self.assertEqual(imported.title, 'Зив сверка')
            draft = imported.drafts.get()
            self.assertEqual(draft.external_id, 'ziv-1.1')
            self.assertEqual(draft.status, TextbookTaskDraft.STATUS_APPROVED)
            self.assertEqual(draft.topic_id, self.topic.pk)
            self.assertEqual(draft.topic_ids, [self.topic.pk])
            self.assertIsNone(draft.imported_task_id)
            self.assertEqual(draft.reviewed_by, self.admin)
            self.assertEqual(imported.assets.count(), 1)
            self.assertEqual(imported.assets.get().stem, 'рис1')
