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

            old_code = self.topic.code
            old_name = self.topic.name
            self.topic.code = 'TEMP.OLD'
            self.topic.name = 'Временная тема'
            self.topic.save()
            self.topic.pk = None
            self.topic.code = old_code
            self.topic.name = old_name
            self.topic.save()
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
            self.assertIsNone(draft.reviewed_by)
            self.assertEqual(imported.assets.count(), 1)
            self.assertEqual(imported.assets.get().stem, 'рис1')

    def _package(self, suffix='.zip'):
        batch = self._make_batch(profile='ziv', title='Перенос')
        TextbookImportAsset.objects.create(batch=batch, stem='рис1', original_name='рис1.png',
                                          file=ContentFile(TINY_PNG, name='рис1.png'))
        dest = Path(self.tmp.name) / ('package' + suffix)
        payload = export_batches(dest, batches=[batch])
        return batch, dest, payload

    def test_zip_preserves_blocks_labels_and_repeated_import(self):
        from problems.models import TaskBlock
        from problems.textbook_transfer import serialize_batch
        with self.settings(MEDIA_ROOT=str(self.media)):
            batch = self._make_batch(profile='ziv', title='Блок')
            block = TaskBlock.objects.create(source=self.source, key='pair', title='Общее условие', size=2)
            first = batch.drafts.get()
            first.block, first.block_position = block, 1
            first.exam_item_codes = ['OGE_2026_22']
            first.tags = ['задача с параметром', 'построение графика']
            first.text_latex = r'Общее условие: $x^2+\\frac{1}{2}$, таблица и рисунок.'
            first.save()
            first.pk = None
            first.external_id = 'ziv-1.2'
            first.block_position = 2
            first.status = TextbookTaskDraft.STATUS_SKIPPED
            first.save()
            TextbookImportAsset.objects.create(batch=batch, stem='рис1', original_name='рис1.png',
                                              file=ContentFile(TINY_PNG, name='рис1.png'))
            dest = Path(self.tmp.name) / 'block.zip'
            original = export_batches(dest, batches=[batch])['batches'][0]
            imported = import_batches(dest, username='prodadmin')[0]
            self.assertEqual(serialize_batch(imported)['drafts'], original['drafts'])
            self.assertEqual(serialize_batch(imported)['blocks'], original['blocks'])
            # Повтор после ручной правки не затирает работу редактора.
            imported.drafts.filter(block_position=1).update(text_latex='Ручная правка')
            again = import_batches(dest, username='prodadmin')[0]
            self.assertEqual(again.pk, imported.pk)
            self.assertEqual(again.drafts.get(block_position=1).text_latex, 'Ручная правка')
            self.assertEqual(TextbookImportBatch.objects.count(), 2)

    def test_check_only_does_not_create_records(self):
        with self.settings(MEDIA_ROOT=str(self.media)):
            _, dest, _ = self._package()
            import_batches(dest, username='prodadmin', check_only=True)
            self.assertEqual(TextbookImportBatch.objects.count(), 1)
            self.assertEqual(TextbookImportAsset.objects.count(), 1)

    def test_missing_or_corrupt_image_rejected_before_writes(self):
        from problems.textbook_transfer import TextbookTransferError
        with self.settings(MEDIA_ROOT=str(self.media)):
            _, dest, _ = self._package(suffix='')
            image = next((dest / 'assets').rglob('*.png'))
            image.write_bytes(b'corrupt')
            with self.assertRaisesRegex(TextbookTransferError, 'контрольная сумма'):
                import_batches(dest, username='prodadmin')
            image.unlink()
            with self.assertRaisesRegex(TextbookTransferError, 'Нет рисунка'):
                import_batches(dest, username='prodadmin')
            self.assertEqual(TextbookImportBatch.objects.count(), 1)

    def test_missing_dictionary_code_rejected(self):
        import json
        from problems.textbook_transfer import TextbookTransferError
        with self.settings(MEDIA_ROOT=str(self.media)):
            _, dest, payload = self._package(suffix='')
            payload['batches'][0]['drafts'][0]['exam_item_codes'] = ['MISSING']
            (dest / 'batches.json').write_text(json.dumps(payload))
            with self.assertRaisesRegex(TextbookTransferError, 'MISSING'):
                import_batches(dest, username='prodadmin')
            self.assertEqual(TextbookImportBatch.objects.count(), 1)

    def test_failed_asset_write_rolls_back_database_and_files(self):
        from unittest.mock import patch
        with self.settings(MEDIA_ROOT=str(self.media)):
            _, dest, _ = self._package()
            before = {p for p in self.media.rglob('*') if p.is_file()}
            with patch.object(TextbookImportAsset, 'save', side_effect=RuntimeError('ошибка записи')):
                with self.assertRaises(RuntimeError):
                    import_batches(dest, username='prodadmin')
            self.assertEqual(TextbookImportBatch.objects.count(), 1)
            self.assertEqual({p for p in self.media.rglob('*') if p.is_file()}, before)

    def test_zip_traversal_rejected(self):
        import zipfile
        from problems.textbook_transfer import TextbookTransferError
        dest = Path(self.tmp.name) / 'unsafe.zip'
        with zipfile.ZipFile(dest, 'w') as archive:
            archive.writestr('../outside.txt', 'no')
        with self.assertRaisesRegex(TextbookTransferError, 'Недопустимый путь'):
            import_batches(dest, username='prodadmin')


class TransferScriptTests(TestCase):
    def setUp(self):
        import importlib.util
        path = Path(__file__).resolve().parents[2] / 'tools/transfer_textbook_batch.py'
        spec = importlib.util.spec_from_file_location('transfer_script', path)
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)

    def test_preflight_failure_does_not_upload(self):
        import subprocess
        from unittest.mock import patch
        with patch.object(self.script, 'run', side_effect=subprocess.CalledProcessError(1, 'ssh')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                self.script.transfer(Path('batch.zip'), 'teacher@example.com', '/srv/egormath', 'egor')
        self.assertEqual(run.call_count, 1)
        self.assertIn('SCHEMA_VERSION', run.call_args.args[0][-1])

    def test_transfer_checks_before_import_and_removes_only_its_temp_file(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'batch.zip'
            package.write_bytes(b'zip')
            with patch.object(self.script, 'run', return_value=SimpleNamespace(stdout='/tmp/egormath-transfer.ABC123\n')) as run:
                self.script.transfer(package, 'teacher@example.com', '/srv/egormath', 'egor')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[2][0], 'scp')
        self.assertIn('sha256', commands[3][-1])
        self.assertIn('--check-only', commands[4][-1])
        self.assertIn('import_textbook_batches', commands[5][-1])
        self.assertNotIn('--check-only', commands[5][-1])
        self.assertEqual(commands[6][-1], 'rm -f /tmp/egormath-transfer.ABC123/batch.zip && rmdir /tmp/egormath-transfer.ABC123')
        self.assertFalse(any('deploy.sh' in str(c) or 'git pull' in str(c) for c in commands))
