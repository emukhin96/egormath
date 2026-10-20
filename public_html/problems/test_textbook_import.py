import io
import json
import zipfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from problems.models import (Source, Task, TaskImage, TaskSource, TaskSubitem,
                             TaskTopic,
                             TextbookImportBatch, TextbookTaskDraft, Topic)
from problems.tests import make_teacher
from problems.textbook_import import (TextbookImportError, attach_image_archive,
                                      commit_batch, create_batch_from_bundle,
                                      missing_imported_collection_draft_ids,
                                      normalize_image_stem,
                                      repair_ziv_batch_leaks,
                                      sync_batch_draft_images,
                                      ziv_variant_summary)
from problems.textbook_parser import parse_ziv
from problems.textbook_topics import (match_topic_candidates, set_draft_topics,
                                      suggested_topic_for_drafts)
from worksheets.models import Collection, WorksheetItem


TINY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
    b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
)


def bundle(**task_overrides):
    task = {
        'external_id': '1.2.37',
        'source_number': '37',
        'source_path': ['Алгебра', 'Квадратные уравнения'],
        'collection_key': 'alg.quadratic',
        'collection_title': 'Квадратные уравнения',
        'topic_original': 'Квадратные уравнения',
        'text_latex': 'Решите $x^2=4$.',
        'subitems': [],
        'author_answer_latex': '$x=\\pm2$',
        'author_solution_latex': 'Извлечём квадратный корень.',
        'confidence': 1,
        'warnings': [],
        'stars': 3,
    }
    task.update(task_overrides)
    return {'schema_version': 1, 'profile': 'book-with-answers',
            'diagnostics': {'pages': 10}, 'tasks': [task]}


class TextbookImportTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()

    def create_batch(self, payload=None):
        return create_batch_from_bundle(
            payload or bundle(), user=self.teacher, title='Пробная партия',
            source_title='Тестовый задачник', source_author='Автор')

    def test_formula_worker_failure_does_not_interrupt_batch_drafts(self):
        from assignments.checks import formulas
        payload = bundle(text_latex='Упростите выражение.', author_answer_latex='$a+173$')
        payload['tasks'].append({**payload['tasks'][0], 'external_id': '1.2.38',
                                 'source_number': '38', 'author_answer_latex': '$4$'})
        formulas._checked.cache_clear()
        with patch.object(formulas, '_run_worker',
                          side_effect=formulas.FormulaUnavailable('сбой')):
            batch = self.create_batch(payload)
        drafts = list(batch.drafts.order_by('source_number'))
        self.assertEqual(len(drafts), 2)
        self.assertEqual(drafts[0].author_answer_latex, '$a+173$')
        self.assertEqual(drafts[0].answer_mask, '')
        self.assertEqual(drafts[1].answer_mask, '{{number: 4}}')

    def test_corrupt_late_zip_member_does_not_replace_existing_assets(self):
        import tempfile
        from pathlib import Path
        from .models import TextbookImportAsset

        with tempfile.TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            batch = self.create_batch()

            def archive(first, second):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as zip_file:
                    zip_file.writestr('first.png', first)
                    zip_file.writestr('second.png', second)
                return stream.getvalue()

            attach_image_archive(batch, SimpleUploadedFile(
                'images.zip', archive(TINY_PNG, TINY_PNG)))
            before = list(batch.assets.order_by('pk').values('pk', 'file'))
            files_before = sorted(str(p) for p in Path(media).rglob('*') if p.is_file())
            # Центральный каталог остаётся читаемым, CRC второго файла неверна.
            damaged = archive(b'new-first-image', b'unique-second-image')
            damaged = damaged.replace(b'unique-second-image', b'broken-second-image')
            with self.assertRaisesMessage(TextbookImportError, 'second.png'):
                attach_image_archive(batch, SimpleUploadedFile('images.zip', damaged))
            self.assertEqual(list(batch.assets.order_by('pk').values('pk', 'file')), before)
            self.assertEqual(sorted(str(p) for p in Path(media).rglob('*') if p.is_file()),
                             files_before)
            for asset in TextbookImportAsset.objects.filter(batch=batch):
                self.assertEqual(Path(asset.file.path).read_bytes(), TINY_PNG)

    def test_detail_exposes_missing_task_and_structure_diagnostics(self):
        payload = bundle()
        payload['diagnostics'] = {'missing_task_ids': ['1.1', '6.1'],
                                  'paragraphs_without_structure': [23, 24]}
        batch = self.create_batch(payload)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('textbook_import_detail', args=[batch.pk]))
        self.assertContains(response, 'Не найдены номера задач: 1.1, 6.1')
        self.assertContains(response, 'Не распознаны разделы оглавления: 23, 24')

    def test_area_answer_units_survive_upload_and_repeated_normalization(self):
        from .textbook_parser import apply_imported_answer
        for answer in (r'$300$ см$^{2}$', r'$37,5$ см$^{2}$',
                       r'$2$ м$^{3}$', r'$-12$ см$^{2}$'):
            with self.subTest(answer=answer):
                self.assertEqual(apply_imported_answer(answer), answer)
                batch = self.create_batch(bundle(author_answer_latex=answer))
                saved = batch.drafts.get().author_answer_latex
                self.assertEqual(saved, answer)
                self.assertEqual(apply_imported_answer(saved), answer)
        self.assertEqual(apply_imported_answer(r'2$ км/ч$'), r'$2$ км/ч')

    def test_deferred_subitems_are_read_only_on_review_and_completed_on_commit(self):
        from .textbook_import import DEFERRED_MASK_WARNING
        payload = bundle(subitems=[
            {'label': 'а', 'text_latex': 'Первый пункт',
             'author_answer_latex': '$3$'},
            {'label': 'б', 'text_latex': 'Второй пункт',
             'author_answer_latex': '$7$'},
            {'label': 'в', 'text_latex': 'Третий пункт',
             'author_answer_latex': '$8$', 'answer_mask': '{{number: 8}}'},
        ])
        # Бюджет исчерпан между первым и вторым пунктами, без реального сна.
        with patch('problems.textbook_import.monotonic', side_effect=[0, 0, 3]):
            batch = self.create_batch(payload)
        draft = batch.drafts.get()
        self.assertEqual(draft.subitems[0]['answer_mask'], '{{number: 3}}')
        self.assertEqual(draft.subitems[1]['answer_mask'], '')
        self.assertEqual(draft.subitems[2]['answer_mask'], '{{number: 8}}')
        self.assertIn(DEFERRED_MASK_WARNING, draft.warnings)
        draft.warnings.append('Проверить рисунок')
        draft.subitems[0]['answer_mask'] = '{{number: 4}}'
        draft.save()
        self.client.force_login(self.teacher)
        url = reverse('textbook_import_review', args=[batch.pk, draft.pk])
        with patch('assignments.checks.draft_mask') as generate:
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.head(url).status_code, 200)
            generate.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.subitems[1]['answer_mask'], '')
        self.assertIn(DEFERRED_MASK_WARNING, draft.warnings)
        draft.topic = Topic.objects.create(name='Тема отложенных пунктов')
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save()
        commit_batch(batch, user=self.teacher)
        draft.refresh_from_db()
        self.assertEqual(draft.subitems[0]['answer_mask'], '{{number: 4}}')
        self.assertEqual(draft.subitems[1]['answer_mask'], '{{number: 7}}')
        self.assertNotIn(DEFERRED_MASK_WARNING, draft.warnings)
        self.assertIn('Проверить рисунок', draft.warnings)
        self.assertEqual(list(TaskSubitem.objects.order_by('order').values_list(
            'answer_mask', flat=True)),
            ['{{number: 4}}', '{{number: 7}}', '{{number: 8}}'])

    def test_clean_approval_ignores_only_pending_masks(self):
        payload = bundle(author_answer_latex='$42$')
        payload['tasks'].extend([
            dict(payload['tasks'][0], external_id='2', warnings=['Проверить условие']),
            dict(payload['tasks'][0], external_id='3', confidence=0.5),
            dict(payload['tasks'][0], external_id='4'),
        ])
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Тема массового одобрения')
        batch.drafts.exclude(external_id='4').update(topic=topic)
        batch.drafts.filter(external_id='4').update(topic=None)
        self.client.force_login(self.teacher)
        with patch('assignments.checks.draft_mask') as generate:
            response = self.client.post(reverse('textbook_import_approve_clean', args=[batch.pk]))
            generate.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(batch.drafts.filter(
            status=TextbookTaskDraft.STATUS_APPROVED).values_list('external_id', flat=True)),
            ['1.2.37'])
        commit_batch(batch, user=self.teacher, require_complete=False)
        self.assertEqual(Task.objects.get().answer_mask, '{{number: 42}}')

    def test_bulk_approval_then_direct_commit_completes_pending_masks(self):
        from .textbook_import import DEFERRED_MASK_WARNING
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            batch = self.create_batch(bundle(author_answer_latex='$42$'))
        batch.drafts.update(topic=Topic.objects.create(name='Тема массового выбора'))
        draft = batch.drafts.get()
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('textbook_import_bulk', args=[batch.pk]), {
            'ids': [draft.pk], 'status': TextbookTaskDraft.STATUS_APPROVED,
        })
        self.assertEqual(response.status_code, 302)
        commit_batch(batch, user=self.teacher)
        draft.refresh_from_db()
        self.assertEqual(draft.imported_task.answer_mask, '{{number: 42}}')
        self.assertNotIn(DEFERRED_MASK_WARNING, draft.warnings)

    def test_publication_resumes_short_posts_and_publishes_all_masks(self):
        from .textbook_import import DEFERRED_MASK_WARNING
        payload = bundle(author_answer_latex='$42$')
        payload['tasks'].extend([
            dict(payload['tasks'][0], external_id=str(i), text_latex=f'Найдите число {i}.')
            for i in range(2, 4)
        ])
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Тема пошаговой публикации')
        batch.drafts.update(topic=topic)
        self.client.force_login(self.teacher)
        self.client.post(reverse('textbook_import_approve_clean', args=[batch.pk]))
        url = reverse('textbook_import_commit', args=[batch.pk])
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            for remaining in (2, 1):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['remaining'], remaining)
                self.assertEqual(Task.objects.count(), 0)
            self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(Task.objects.count(), 3)
        self.assertEqual(set(Task.objects.values_list('answer_mask', flat=True)),
                         {'{{number: 42}}'})
        self.assertTrue(all(DEFERRED_MASK_WARNING not in d.warnings
                            for d in batch.drafts.all()))
        with patch('assignments.checks.draft_mask') as generate:
            self.assertEqual(self.client.post(url).status_code, 302)
            generate.assert_not_called()
        self.assertEqual(Task.objects.count(), 3)

    def test_section_preparation_leaves_other_sections_pending(self):
        from .textbook_import import DEFERRED_MASK_WARNING
        payload = bundle(author_answer_latex='$42$')
        payload['tasks'].extend([
            dict(payload['tasks'][0], external_id='2', text_latex='Вторая задача.'),
            dict(payload['tasks'][0], external_id='3', source_path=['Другая глава'],
                 collection_key='other', collection_title='Другая глава'),
        ])
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Тема выбранного раздела')
        batch.drafts.update(topic=topic, status=TextbookTaskDraft.STATUS_APPROVED)
        self.client.force_login(self.teacher)
        detail = self.client.get(reverse('textbook_import_detail', args=[batch.pk]))
        section = next(g for g in detail.context['collection_groups']
                       if g['is_leaf'] and g['path'][-1] == 'Квадратные уравнения')
        url = reverse('textbook_import_commit_section', args=[batch.pk])
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            response = self.client.post(url, {'section': section['token']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['section'], section['token'])
            self.assertContains(response, 'name="section"')
            self.assertEqual(self.client.post(url, {'section': section['token']}).status_code, 302)
        other = batch.drafts.get(external_id='3')
        self.assertEqual(other.status, TextbookTaskDraft.STATUS_APPROVED)
        self.assertEqual(other.answer_mask, '')
        self.assertIn(DEFERRED_MASK_WARNING, other.warnings)
        self.assertEqual(Task.objects.count(), 2)

    def test_expired_mask_budget_preserves_answers_and_other_tasks(self):
        from .textbook_import import DEFERRED_MASK_WARNING
        payload = bundle(author_answer_latex='$42$')
        payload['tasks'].append(dict(payload['tasks'][0], external_id='2'))
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0), \
                patch('assignments.checks.draft_mask') as generate:
            batch = self.create_batch(payload)
            generate.assert_not_called()
        self.assertEqual(batch.drafts.count(), 2)
        for draft in batch.drafts.all():
            self.assertEqual(draft.author_answer_latex, '$42$')
            self.assertEqual(draft.answer_mask, '')
            self.assertIn(DEFERRED_MASK_WARNING, draft.warnings)

    def test_topic_matching_is_reused_only_within_same_batch(self):
        payload = bundle()
        payload['tasks'].extend([
            dict(payload['tasks'][0], external_id='2'),
            dict(payload['tasks'][0], external_id='3', topic_original='Другая тема'),
        ])
        with patch('problems.textbook_topics.match_topic_candidates',
                   wraps=match_topic_candidates) as match:
            first = self.create_batch(payload)
            self.assertEqual(match.call_count, 2)
            self.create_batch(payload)
            self.assertEqual(match.call_count, 4)
        self.assertEqual(first.drafts.get(external_id='2').topic_candidates,
                         first.drafts.order_by('pk').first().topic_candidates)

    def test_backfill_clears_deferred_warning_only_when_applied(self):
        from .textbook_import import DEFERRED_MASK_WARNING
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            batch = self.create_batch(bundle(author_answer_latex='$7$'))
        call_command('backfill_textbook_masks', batch.pk, stdout=io.StringIO())
        self.assertIn(DEFERRED_MASK_WARNING, batch.drafts.get().warnings)
        call_command('backfill_textbook_masks', batch.pk, apply=True,
                     stdout=io.StringIO())
        draft = batch.drafts.get()
        self.assertEqual(draft.answer_mask, '{{number: 7}}')
        self.assertNotIn(DEFERRED_MASK_WARNING, draft.warnings)

    def test_mask_is_generated_and_transferred_to_task(self):
        batch = self.create_batch(bundle(
            text_latex='Найдите длину отрезка.',
            author_answer_latex='$42$ см'))
        draft = batch.drafts.get()
        self.assertEqual(draft.answer_mask, '{{number: 42}} см')
        draft.topic = Topic.objects.create(name='Тема с маской')
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save(update_fields=['topic', 'status'])

        commit_batch(batch, user=self.teacher)

        draft.refresh_from_db()
        self.assertEqual(draft.imported_task.answer_mask, '{{number: 42}} см')

    def test_subitem_masks_are_generated_and_transferred(self):
        batch = self.create_batch(bundle(
            text_latex='Ответьте на вопросы.',
            author_answer_latex='',
            subitems=[
                {'label': 'а', 'text_latex': 'Найдите число.',
                 'author_answer_latex': '$3$'},
                {'label': 'б', 'text_latex': 'Докажите утверждение.',
                 'author_answer_latex': ''},
            ]))
        draft = batch.drafts.get()
        self.assertEqual(draft.answer_mask, '')
        self.assertEqual(draft.subitems[0]['answer_mask'], '{{number: 3}}')
        self.assertEqual(draft.subitems[1]['answer_mask'], '')
        draft.topic = Topic.objects.create(name='Тема подпунктов с маской')
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save(update_fields=['topic', 'status'])

        commit_batch(batch, user=self.teacher)

        masks = list(TaskSubitem.objects.order_by('order').values_list(
            'answer_mask', flat=True))
        self.assertEqual(masks, ['{{number: 3}}', ''])

    def test_invalid_import_mask_is_rejected(self):
        with self.assertRaisesMessage(TextbookImportError,
                                      'Некорректная маска answer_mask'):
            self.create_batch(bundle(answer_mask='{{number: не число}}'))

    def test_backfill_masks_has_dry_run_and_apply_modes(self):
        batch = self.create_batch(bundle(
            text_latex='Найдите число.', author_answer_latex='$7$'))
        batch.drafts.update(answer_mask='')

        call_command('backfill_textbook_masks', batch.pk, stdout=io.StringIO())
        self.assertEqual(batch.drafts.get().answer_mask, '')

        call_command(
            'backfill_textbook_masks', batch.pk, apply=True,
            stdout=io.StringIO())
        self.assertEqual(batch.drafts.get().answer_mask, '{{number: 7}}')

    def test_backfill_transfers_masks_to_already_imported_tasks(self):
        topic = Topic.objects.create(name='Тема повторной заливки')
        batch = self.create_batch(bundle(
            text_latex='Найдите число.', author_answer_latex='$7$'))
        draft = batch.drafts.get()
        draft.topic = topic
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save(update_fields=['topic', 'status'])
        commit_batch(batch, user=self.teacher)
        draft.refresh_from_db()
        task = draft.imported_task
        task.answer_mask = ''
        task.save(update_fields=['answer_mask'])
        draft.answer_mask = ''
        draft.save(update_fields=['answer_mask'])

        call_command(
            'backfill_textbook_masks', batch.pk, apply=True,
            stdout=io.StringIO())

        task.refresh_from_db()
        self.assertEqual(task.answer_mask, '{{number: 7}}')

    def test_backfill_preserves_manual_mask_on_imported_task(self):
        topic = Topic.objects.create(name='Тема ручной маски')
        batch = self.create_batch(bundle(
            text_latex='Найдите число.', author_answer_latex='$7$'))
        draft = batch.drafts.get()
        draft.topic = topic
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save(update_fields=['topic', 'status'])
        commit_batch(batch, user=self.teacher)
        draft.refresh_from_db()
        task = draft.imported_task
        task.answer_mask = '{{number: 8}}'
        task.save(update_fields=['answer_mask'])

        call_command(
            'backfill_textbook_masks', batch.pk, apply=True,
            stdout=io.StringIO())

        task.refresh_from_db()
        self.assertEqual(task.answer_mask, '{{number: 8}}')

    def test_backfill_transfers_subitem_masks_to_imported_task(self):
        topic = Topic.objects.create(name='Тема подпунктов')
        batch = self.create_batch(bundle(
            text_latex='Ответьте на вопрос.', author_answer_latex='',
            subitems=[{
                'label': 'а', 'text_latex': 'Найдите число.',
                'author_answer_latex': '$3$',
            }]))
        draft = batch.drafts.get()
        draft.topic = topic
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save(update_fields=['topic', 'status'])
        commit_batch(batch, user=self.teacher)
        draft.refresh_from_db()
        subitem = draft.imported_task.subitems.get()
        subitem.answer_mask = ''
        subitem.save(update_fields=['answer_mask'])
        draft.subitems[0]['answer_mask'] = ''
        draft.save(update_fields=['subitems'])

        call_command(
            'backfill_textbook_masks', batch.pk, apply=True,
            stdout=io.StringIO())

        subitem.refresh_from_db()
        self.assertEqual(subitem.answer_mask, '{{number: 3}}')

    def test_ziv_summary_uses_one_query_for_all_drafts(self):
        batch = self.create_batch(bundle(external_id='sr/09/v1/1'))
        batch.profile = 'ziv'
        batch.save(update_fields=['profile'])
        TextbookTaskDraft.objects.bulk_create([
            TextbookTaskDraft(
                batch=batch, external_id=f'sr/09/v2/{number}',
                source_number=str(number), source_path=['Работа', 'Тема'],
                collection_title='Тема', text_latex=f'Задача {number}')
            for number in range(2, 22)
        ])

        with self.assertNumQueries(1):
            summary = ziv_variant_summary(batch)

        self.assertEqual(sum(row['total'] for row in summary), 21)

    def test_missing_collection_check_does_not_query_each_draft(self):
        batch = self.create_batch()
        task = Task.objects.create(text_latex='Опубликованная задача')
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_IMPORTED,
            imported_task=task)
        TextbookTaskDraft.objects.bulk_create([
            TextbookTaskDraft(
                batch=batch, external_id=f'published-{number}',
                source_number=str(number), source_path=['Глава', 'Раздел'],
                collection_key='chapter.section',
                collection_title='Раздел', text_latex=f'Задача {number}',
                status=TextbookTaskDraft.STATUS_IMPORTED,
                imported_task=task)
            for number in range(2, 22)
        ])

        with self.assertNumQueries(2):
            missing = missing_imported_collection_draft_ids(batch)

        self.assertEqual(len(missing), 21)

    def test_section_detail_queries_do_not_scale_with_drafts(self):
        batch = self.create_batch(bundle(source_path=['Глава', 'Раздел']))
        self.client.force_login(self.teacher)
        url = reverse('textbook_import_detail', args=[batch.pk])
        landing = self.client.get(url)
        section = next(
            group for group in landing.context['collection_groups']
            if group['is_leaf'])
        with CaptureQueriesContext(connection) as single_queries:
            self.client.get(url, {'section': section['token']})
        TextbookTaskDraft.objects.bulk_create([
            TextbookTaskDraft(
                batch=batch, external_id=f'section-{number}',
                source_number=str(number), source_path=['Глава', 'Раздел'],
                collection_key='alg.quadratic',
                collection_title='Квадратные уравнения',
                text_latex=f'Задача {number}')
            for number in range(2, 22)
        ])

        with CaptureQueriesContext(connection) as many_queries:
            response = self.client.get(url, {'section': section['token']})

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(many_queries), len(single_queries) + 2)

    def test_section_retry_is_noop_and_can_restore_membership(self):
        from worksheets.models import WorksheetItem
        batch = self.create_batch(bundle(source_path=['Глава', 'Раздел']))
        draft = batch.drafts.get()
        draft.topic = Topic.objects.create(name='Тема повторной публикации')
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save()
        commit_batch(batch, user=self.teacher, draft_ids=[draft.pk], require_complete=False)
        before = (Task.objects.count(), WorksheetItem.objects.count())
        result = commit_batch(batch, user=self.teacher, draft_ids=[draft.pk], require_complete=False)
        self.assertEqual(result, {'created': 0, 'reused': 0, 'collections': 0})
        self.assertEqual((Task.objects.count(), WorksheetItem.objects.count()), before)
        draft.refresh_from_db()
        WorksheetItem.objects.filter(task_id=draft.imported_task_id).delete()
        commit_batch(batch, user=self.teacher, draft_ids=[draft.pk], require_complete=False)
        self.assertEqual((Task.objects.count(), WorksheetItem.objects.count()), before)
        self.client.force_login(self.teacher)
        detail = self.client.get(reverse('textbook_import_detail', args=[batch.pk]))
        section = next(g for g in detail.context['collection_groups'] if g['is_leaf'])
        response = self.client.post(reverse('textbook_import_commit_section', args=[batch.pk]),
                                    {'section': section['token']}, follow=True)
        self.assertContains(response, 'уже загружен')

    def test_section_retry_recreates_deleted_task(self):
        batch = self.create_batch()
        batch.drafts.update(topic=Topic.objects.create(name='Восстановление'),
                            status=TextbookTaskDraft.STATUS_APPROVED)
        commit_batch(batch, user=self.teacher)
        draft = batch.drafts.get()
        WorksheetItem.objects.filter(task=draft.imported_task).delete()
        draft.imported_task.delete()
        draft.refresh_from_db()
        self.assertIsNone(draft.imported_task_id)
        self.assertEqual(draft.status, TextbookTaskDraft.STATUS_IMPORTED)
        result = commit_batch(batch, user=self.teacher, draft_ids=[draft.pk],
                              require_complete=False)
        self.assertEqual(result['created'], 1)
        draft.refresh_from_db()
        self.assertIsNotNone(draft.imported_task_id)
        self.assertTrue(WorksheetItem.objects.filter(task=draft.imported_task).exists())
        self.assertEqual(commit_batch(batch, user=self.teacher)['created'], 0)

    def test_orphaned_import_reuses_existing_source_key(self):
        batch = self.create_batch()
        batch.drafts.update(topic=Topic.objects.create(name='Повтор ключа'),
                            status=TextbookTaskDraft.STATUS_APPROVED)
        commit_batch(batch, user=self.teacher)
        task_id = batch.drafts.get().imported_task_id
        batch.drafts.update(imported_task=None)
        result = commit_batch(batch, user=self.teacher)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['reused'], 1)
        self.assertEqual(batch.drafts.get().imported_task_id, task_id)

    def test_orphaned_import_keeps_validation_and_rolls_back(self):
        batch = self.create_batch()
        batch.drafts.update(status=TextbookTaskDraft.STATUS_IMPORTED, topic=None)
        with self.assertRaisesRegex(TextbookImportError, 'не выбрана тема'):
            commit_batch(batch, user=self.teacher)
        self.assertEqual(batch.drafts.get().status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(Task.objects.count(), 0)

    def test_orphaned_import_does_not_restore_unselected_drafts(self):
        payload = bundle()
        payload['tasks'].append(dict(payload['tasks'][0], external_id='other'))
        batch = self.create_batch(payload)
        batch.drafts.update(topic=Topic.objects.create(name='Выбранный раздел'),
                            status=TextbookTaskDraft.STATUS_IMPORTED)
        selected = batch.drafts.first()
        commit_batch(batch, user=self.teacher, draft_ids=[selected.pk],
                     require_complete=False)
        other = batch.drafts.exclude(pk=selected.pk).get()
        self.assertIsNone(other.imported_task_id)
        self.assertEqual(other.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(Task.objects.count(), 1)

    def test_section_failure_rolls_back_and_preserves_selected_section(self):
        from unittest.mock import patch
        from . import textbook_import
        payload = bundle(source_path=['Глава', 'Раздел'])
        payload['tasks'].append(dict(payload['tasks'][0], external_id='1.2.38', source_number='38'))
        batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Тема отката')
        batch.drafts.update(topic=topic, status=TextbookTaskDraft.STATUS_APPROVED)
        self.client.force_login(self.teacher)
        detail = self.client.get(reverse('textbook_import_detail', args=[batch.pk]))
        section = next(g for g in detail.context['collection_groups'] if g['is_leaf'])
        original = textbook_import._add_draft_task_to_collection
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TextbookImportError('Ошибка проверки раздела')
            return original(*args, **kwargs)
        with patch.object(textbook_import, '_add_draft_task_to_collection', side_effect=fail_second):
            response = self.client.post(reverse('textbook_import_commit_section', args=[batch.pk]),
                                        {'section': section['token']})
        self.assertIn('section=' + section['token'], response.url)
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(batch.drafts.filter(status=TextbookTaskDraft.STATUS_APPROVED).count(), 2)
        response = self.client.get(response.url)
        self.assertContains(response, 'Ошибка проверки раздела')
        self.assertTrue(response.context['selected_group']['can_commit'])

    def test_upload_creates_only_drafts(self):
        self.client.login(username='teacher1', password='pass12345')
        upload = SimpleUploadedFile(
            'import.json', json.dumps(bundle()).encode(),
            content_type='application/json')
        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Партия', 'source_title': 'Задачник',
            'source_author': 'Автор',
            'input_kind': 'json', 'bundle': upload,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TextbookImportBatch.objects.count(), 1)
        self.assertEqual(TextbookTaskDraft.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 0)

    def test_upload_parses_tex_with_answers_at_end(self):
        self.client.login(username='teacher1', password='pass12345')
        source = r"""
\section*{Тема}
\item[1.1.] Найдите $1+1$.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. 2.
"""
        upload = SimpleUploadedFile(
            'book.tex', source.encode(), content_type='text/plain')

        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'TEX с ответами', 'source_title': 'Задачник',
            'input_kind': 'answers_end', 'tasks_tex': upload,
        })

        self.assertEqual(response.status_code, 302)
        draft = TextbookTaskDraft.objects.get()
        self.assertEqual(draft.author_answer_latex, '2')
        self.assertEqual(draft.batch.profile, 'galitsky')
        self.assertEqual(Task.objects.count(), 0)

    def test_upload_parses_separate_solution_tex(self):
        self.client.login(username='teacher1', password='pass12345')
        tasks = SimpleUploadedFile(
            'tasks.tex', b'1.1.A01 Find $1+1$.',
            content_type='text/plain')
        solutions = SimpleUploadedFile(
            'solutions.tex', b'1.1.A01 Answer: 2.',
            content_type='text/plain')

        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Два TEX', 'source_title': 'Задачник',
            'input_kind': 'separate_solutions',
            'tasks_tex': tasks, 'solutions_tex': solutions,
        })

        self.assertEqual(response.status_code, 302)
        draft = TextbookTaskDraft.objects.get()
        self.assertEqual(draft.batch.profile, 'shestakov')
        self.assertEqual(draft.source_path, [
            'Глава 1. Числовые выражения',
            '§1. Действия с целыми числами',
        ])
        self.assertEqual(Task.objects.count(), 0)

    def test_separate_solution_layout_requires_second_tex(self):
        self.client.login(username='teacher1', password='pass12345')
        tasks = SimpleUploadedFile(
            'tasks.tex', b'1.1.A01 Find $1+1$.',
            content_type='text/plain')

        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Без решебника', 'source_title': 'Задачник',
            'input_kind': 'separate_solutions', 'tasks_tex': tasks,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Выберите TEX с авторскими решениями')
        self.assertEqual(TextbookImportBatch.objects.count(), 0)

    def test_duplicate_legacy_sources_choose_first(self):
        from problems.models import Source
        first = Source.objects.create(
            title='Повтор', author='Автор', year=2000)
        Source.objects.create(title='Повтор', author='Автор', year=2000)
        batch = create_batch_from_bundle(
            bundle(), user=self.teacher, title='Партия',
            source_title='Повтор', source_author='Автор', source_year=2000)
        self.assertEqual(batch.source, first)

    def test_non_finite_confidence_does_not_crash_upload(self):
        batch = self.create_batch(bundle(confidence='NaN'))
        self.assertEqual(batch.drafts.get().confidence, 0)

    def test_task_with_only_subitems_can_be_uploaded_and_reviewed(self):
        payload = bundle(text_latex='', subitems=[{
            'label': 'а', 'text_latex': 'Первый подпункт.',
            'author_solution_latex': 'Решение подпункта.',
        }], author_answer_latex='Общий ответ.',
            author_solution_latex='Общее решение.')
        batch = self.create_batch(payload)
        draft = batch.drafts.get()
        self.assertEqual(draft.text_latex, '')
        self.assertEqual(draft.author_answer_latex, 'Общий ответ.')
        self.assertEqual(draft.author_solution_latex, 'Общее решение.')
        self.assertEqual(
            draft.subitems[0]['author_solution_latex'],
            'Решение подпункта.')

        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': '',
                'subitems': json.dumps(draft.subitems),
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })
        self.assertEqual(response.status_code, 302)

    def test_task_without_text_or_subitems_is_rejected(self):
        with self.assertRaisesMessage(
                TextbookImportError, 'не содержит условия или подпунктов'):
            self.create_batch(bundle(text_latex='', subitems=[]))

    def test_images_are_recorded_and_block_commit_without_assets(self):
        topic = Topic.objects.create(name='Тема с рисунком')
        batch = self.create_batch(bundle(images=['figure-1.png']))
        draft = batch.drafts.get()
        self.assertEqual(draft.images, ['figure-1.png'])
        self.assertIn('figure-1.png', ' '.join(draft.warnings))
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.topic = topic
        draft.save()
        with self.assertRaisesMessage(TextbookImportError,
                                      'не загружены изображения'):
            commit_batch(batch, user=self.teacher)
        self.assertEqual(Task.objects.count(), 0)

    def test_commit_requires_review(self):
        batch = self.create_batch()
        with self.assertRaisesMessage(TextbookImportError, 'непроверенных'):
            commit_batch(batch, user=self.teacher, require_complete=True)
        self.assertEqual(Task.objects.count(), 0)

    def test_commit_imports_approved_and_leaves_the_rest(self):
        topic = Topic.objects.create(name='Частичная тема')
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0],
            external_id='1.2.38',
            source_number='38',
            text_latex='Ещё не проверенная задача.'))
        batch = self.create_batch(payload)
        first = batch.drafts.get(external_id='1.2.37')
        first.status = TextbookTaskDraft.STATUS_APPROVED
        first.topic = topic
        first.save()

        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        self.assertEqual(response.context['approved_count'], 1)
        self.assertContains(
            response, 'Непроверенные и конфликтные строки останутся')
        response = self.client.post(
            reverse('textbook_import_commit', args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, reverse('textbook_import_detail', args=[batch.pk]))
        first.refresh_from_db()
        second = batch.drafts.get(external_id='1.2.38')
        batch.refresh_from_db()
        self.assertEqual(first.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(second.status, TextbookTaskDraft.STATUS_REVIEW)
        self.assertEqual(batch.status, TextbookImportBatch.STATUS_REVIEW)
        self.assertEqual(Task.objects.count(), 1)

    def test_commit_requires_rubricator_topic(self):
        batch = self.create_batch(bundle(
            source_path=['Несуществующий раздел задачника'],
            topic_original='Несуществующий раздел задачника',
            collection_key='unknown.section'))
        batch.drafts.update(topic=None, status=TextbookTaskDraft.STATUS_APPROVED)
        with self.assertRaisesMessage(TextbookImportError, 'тема рубрикатора'):
            commit_batch(batch, user=self.teacher)
        self.assertEqual(Task.objects.count(), 0)

    def test_commit_separates_author_data_and_builds_collection(self):
        topic = Topic.objects.create(name='Квадратные уравнения')
        batch = self.create_batch()
        draft = batch.drafts.get()
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        set_draft_topics(draft, [topic.pk], topic.pk)
        draft.save(update_fields=['status'])

        result = commit_batch(batch, user=self.teacher)
        task = Task.objects.get()
        self.assertEqual(result['created'], 1)
        self.assertEqual(task.stars, 0)
        self.assertEqual(task.answer_latex, '')
        self.assertEqual(task.solution_latex, '')
        self.assertEqual(task.author_answer_latex, '$x=\\pm2$')
        self.assertEqual(task.effective_answer_latex, '$x=\\pm2$')
        ref = TaskSource.objects.get(task=task)
        self.assertEqual(ref.locator, '1.2.37')
        self.assertEqual(ref.source_path,
                         ['Алгебра', 'Квадратные уравнения'])
        leaf = Collection.objects.get(
            source_path=['Алгебра', 'Квадратные уравнения'])
        self.assertTrue(leaf.is_published)
        self.assertEqual(leaf.worksheet.title, 'Квадратные уравнения')
        parent = Collection.objects.get(source_path=['Алгебра'])
        self.assertFalse(parent.is_published)
        self.assertEqual(list(leaf.worksheet.topics.all()), [topic])
        self.assertEqual(list(parent.worksheet.topics.all()), [topic])
        self.assertTrue(WorksheetItem.objects.filter(
            worksheet=leaf.worksheet, task=task).exists())
        self.assertEqual(list(task.topics.all()), [topic])
        self.assertFalse(WorksheetItem.objects.filter(
            worksheet=leaf.worksheet, rubric__gt='').exists())

        self.assertEqual(commit_batch(batch, user=self.teacher), {
            'created': 0, 'reused': 0, 'collections': 0})
        self.assertEqual(Task.objects.count(), 1)

    def test_commit_assigns_exam_grade_and_tags(self):
        from problems.rubricator import seed_rubricator
        seed_rubricator()
        topic = Topic.objects.get(code='ARI.03')
        payload = bundle(
            external_id='6.1',
            source_number='6.1',
            source_path=['№6. Дроби', 'Прототипы'],
            collection_key='oge/06/proto',
            collection_title='№6. Дроби — прототипы',
            topic_original='Дроби',
            exam_item_codes=['OGE_2026_06'],
            grade_band_codes=['GRADE_9'],
            tags=['DEMO'],
            author_answer_latex='15,3',
            text_latex='Найдите $5,6+9,7$.',
        )
        batch = self.create_batch(payload)
        draft = batch.drafts.get()
        self.assertEqual(draft.exam_item_codes, ['OGE_2026_06'])
        self.assertEqual(draft.grade_band_codes, ['GRADE_9'])
        self.assertEqual(draft.tags, ['DEMO'])
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        set_draft_topics(draft, [topic.pk], topic.pk)
        draft.save(update_fields=['status', 'topic', 'topic_ids'])
        commit_batch(batch, user=self.teacher)
        task = Task.objects.get()
        leaf = Collection.objects.get(locator='key:oge/06/proto')
        self.assertEqual(leaf.worksheet.title, '№6. Дроби — прототипы')
        self.assertIn(
            'OGE_2026_06',
            list(task.exam_items.values_list('code', flat=True)))
        self.assertIn(
            'GRADE_9',
            list(task.grade_bands.values_list('code', flat=True)))
        self.assertEqual(list(task.tags.values_list('name', flat=True)), ['DEMO'])
        self.assertEqual(task.author_answer_latex, '15,3')
        self.assertEqual(task.answer_mask, '{{decimal: 15,3}}')

    def test_commit_adds_variant_rubrics_inside_topic_collection(self):
        topic = Topic.objects.create(name='Тема вариантов')
        payload = bundle(
            source_path=[
                'Самостоятельные работы',
                'Числовые неравенства',
                'Вариант 1',
            ],
            collection_key='sr/10/v1',
            collection_title='Числовые неравенства',
            source_number='1',
            external_id='sr/10/v1/1',
        )
        payload['tasks'].append(dict(
            payload['tasks'][0],
            external_id='sr/10/v2/1',
            source_number='1',
            collection_key='sr/10/v2',
            collection_title='Числовые неравенства',
            source_path=[
                'Самостоятельные работы',
                'Числовые неравенства',
                'Вариант 2',
            ],
            text_latex='Вторая задача варианта.',
        ))
        batch = self.create_batch(payload)
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(batch, user=self.teacher)

        leaf = Collection.objects.get(is_published=True)
        self.assertEqual(
            leaf.source_path,
            ['Самостоятельные работы', 'Числовые неравенства'])
        self.assertEqual(leaf.locator, 'key:sr/10')
        self.assertEqual(leaf.worksheet.title, 'Числовые неравенства')
        items = list(leaf.worksheet.items.order_by('order', 'pk'))
        self.assertEqual(
            [item.rubric for item in items if item.is_rubric],
            ['Вариант 1', 'Вариант 2'])
        self.assertEqual(sum(1 for item in items if item.task_id), 2)

    def test_partial_commit_restores_variant_heading_when_returning(self):
        topic = Topic.objects.create(name='Тема дозагрузки')
        payload = bundle()
        payload['tasks'] = [dict(
            payload['tasks'][0], external_id=f'sr/10/v{variant}/{number}',
            source_number=str(number), collection_key=f'sr/10/v{variant}',
            source_path=['Самостоятельные работы', 'Неравенства',
                         f'Вариант {variant}'],
            collection_title='Неравенства',
        ) for variant, number in [(1, 1), (2, 1), (1, 2)]]
        batch = self.create_batch(payload)
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        drafts = list(batch.drafts.order_by('pk'))
        for draft in drafts:
            commit_batch(batch, user=self.teacher, draft_ids=[draft.pk],
                         require_complete=False)
        worksheet = Collection.objects.get(is_published=True).worksheet
        items = list(worksheet.items.order_by('order', 'pk'))
        self.assertEqual([item.rubric for item in items if item.is_rubric],
                         ['Вариант 1', 'Вариант 2', 'Вариант 1'])
        self.assertEqual(len(items), 6)
        commit_batch(batch, user=self.teacher)
        self.assertEqual(worksheet.items.count(), 6)

    def test_commit_restores_section_context_with_same_variant_name(self):
        topic = Topic.objects.create(name='Тема возврата в параграф')
        payload = bundle()
        payload['tasks'] = [dict(
            payload['tasks'][0], external_id=f'chapter/{index}',
            source_path=['Глава 1. Алгебра', section, 'Вариант 1'],
            collection_key=f'Глава 1. Алгебра/{section}/v1',
        ) for index, section in enumerate(['§1. Числа', '§2. Дроби',
                                           '§1. Числа', '§1. Числа'])]
        batch = self.create_batch(payload)
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(batch, user=self.teacher)
        worksheet = Collection.objects.get(is_published=True).worksheet
        self.assertEqual(
            list(worksheet.items.filter(task=None).order_by('order', 'pk')
                 .values_list('rubric', flat=True)),
            ['§1. Числа', 'Вариант 1', '§2. Дроби', 'Вариант 1',
             '§1. Числа', 'Вариант 1'])

    def test_commit_chapter_does_not_repeat_section_for_sibling_variants(self):
        self._check_chapter_sibling_variants(partial=False)

    def test_partial_commit_chapter_does_not_repeat_section_for_sibling_variants(self):
        self._check_chapter_sibling_variants(partial=True)

    def _check_chapter_sibling_variants(self, *, partial):
        topic = Topic.objects.create(name='Тема соседних вариантов')
        payload = bundle()
        sequence = [('§1. Числа', 1), ('§1. Числа', 2),
                    ('§2. Дроби', 1), ('§2. Дроби', 2),
                    ('§1. Числа', 1)]
        payload['tasks'] = [dict(
            payload['tasks'][0], external_id=f'chapter/{index}',
            source_path=['Глава 1. Алгебра', section, f'Вариант {variant}'],
            collection_key=f'Глава 1. Алгебра/{section}/v{variant}',
        ) for index, (section, variant) in enumerate(sequence)]
        batch = self.create_batch(payload)
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        if partial:
            for draft in batch.drafts.order_by('pk'):
                commit_batch(batch, user=self.teacher, draft_ids=[draft.pk],
                             require_complete=False)
        else:
            commit_batch(batch, user=self.teacher)
        worksheet = Collection.objects.get(is_published=True).worksheet
        self.assertEqual(
            list(worksheet.items.filter(task=None).order_by('order', 'pk')
                 .values_list('rubric', flat=True)),
            ['§1. Числа', 'Вариант 1', 'Вариант 2',
             '§2. Дроби', 'Вариант 1', 'Вариант 2',
             '§1. Числа', 'Вариант 1'])
        count = worksheet.items.count()
        commit_batch(batch, user=self.teacher)
        self.assertEqual(worksheet.items.count(), count)

    def test_commit_chapter_uses_section_rubrics(self):
        topic = Topic.objects.create(name='Тема главы')
        payload = bundle(
            source_path=[
                'Глава 1. Числовые выражения',
                '§1. Действия с целыми',
            ],
            collection_key=(
                'Глава 1. Числовые выражения/§1. Действия с целыми'),
            collection_title='§1. Действия с целыми',
        )
        payload['tasks'].append(dict(
            payload['tasks'][0],
            external_id='1.2.38',
            source_number='38',
            source_path=[
                'Глава 1. Числовые выражения',
                '§2. Действия с дробями',
            ],
            collection_key=(
                'Глава 1. Числовые выражения/§2. Действия с дробями'),
            collection_title='§2. Действия с дробями',
            text_latex='Вторая задача главы.',
        ))
        batch = self.create_batch(payload)
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(batch, user=self.teacher)

        leaf = Collection.objects.get(is_published=True)
        self.assertEqual(
            leaf.source_path, ['Глава 1. Числовые выражения'])
        self.assertEqual(leaf.worksheet.title, 'Глава 1. Числовые выражения')
        items = list(leaf.worksheet.items.order_by('order', 'pk'))
        self.assertEqual(
            [item.rubric for item in items if item.is_rubric],
            ['§1. Действия с целыми', '§2. Действия с дробями'])
        self.assertEqual(sum(1 for item in items if item.task_id), 2)

    def test_same_text_twice_in_one_source_stays_two_tasks(self):
        payload = bundle()
        second = dict(payload['tasks'][0], external_id='1.2.38',
                      source_number='38')
        payload['tasks'].append(second)
        batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Тема для дублей')
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(batch, user=self.teacher)
        self.assertEqual(Task.objects.count(), 2)
        self.assertEqual(TaskSource.objects.count(), 2)

    def test_same_text_from_another_source_is_not_merged_automatically(self):
        topic = Topic.objects.create(name='Тема двух изданий')
        first = self.create_batch()
        first.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(first, user=self.teacher)
        second = create_batch_from_bundle(
            bundle(), user=self.teacher, title='Другая партия',
            source_title='Другое издание')
        second.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(second, user=self.teacher)
        self.assertEqual(Task.objects.count(), 2)
        self.assertEqual(TaskSource.objects.count(), 2)

    def test_reimport_marks_same_key_as_imported(self):
        topic = Topic.objects.create(name='Тема повторного ключа')
        first = self.create_batch()
        first.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(first, user=self.teacher)
        task = Task.objects.get()
        first.drafts.get().refresh_from_db()
        self.assertEqual(
            first.drafts.get().status, TextbookTaskDraft.STATUS_IMPORTED)

        second = self.create_batch(bundle(text_latex='Другое условие $x=0$.'))
        draft = second.drafts.get()
        self.assertEqual(draft.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(draft.imported_task_id, task.pk)
        self.assertTrue(any('уже есть в базе' in item for item in draft.warnings))
        self.assertEqual(Task.objects.count(), 1)

        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse(
            'textbook_import_detail', args=[second.pk]))
        self.assertContains(response, 'Импортировано')
        self.assertContains(response, reverse('task_detail', args=[task.pk]))
        self.assertContains(response, 'target="_blank"')

    def test_imported_task_without_collection_can_restore_section(self):
        source = Source.objects.create(
            title='Зив', author='Автор')
        payload = bundle(
            external_id='sr/10/v1/1', source_number='1',
            source_path=[
                'Самостоятельные работы',
                'Чётность и нечётность функции',
                'Вариант 1',
            ],
            collection_key='sr/10/v1',
            collection_title='Чётность и нечётность функции')
        task = Task.objects.create(
            text_latex=payload['tasks'][0]['text_latex'],
            created_by=self.teacher, is_shared=True)
        TaskSource.objects.create(
            task=task, source=source, number='1', locator='sr/10/v1/1',
            source_path=payload['tasks'][0]['source_path'])
        batch = create_batch_from_bundle(
            payload, user=self.teacher, title='Зив',
            source_title='Зив', source_author='Автор')
        draft = batch.drafts.get()
        self.assertEqual(draft.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(Collection.objects.count(), 0)

        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        group = next(
            item for item in detail.context['collection_groups']
            if item['is_leaf'])
        detail = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]),
            {'section': group['token']})
        self.assertEqual(detail.context['missing_collection_count'], 1)
        self.assertEqual(
            detail.context['selected_group']['missing_collection_count'], 1)
        self.assertContains(detail, 'Восстановить подборку')

        response = self.client.post(reverse(
            'textbook_import_commit_section', args=[batch.pk]), {
                'section': group['token'],
            })
        self.assertEqual(response.status_code, 302)
        leaf = Collection.objects.get(locator='key:sr/10')
        self.assertTrue(leaf.is_published)
        self.assertTrue(leaf.worksheet.items.filter(task=task).exists())
        self.assertEqual(Task.objects.count(), 1)

        repaired = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]),
            {'section': group['token']})
        self.assertEqual(repaired.context['missing_collection_count'], 0)
        self.assertFalse(repaired.context['selected_group']['can_commit'])

    def test_imported_draft_review_does_not_save_edits(self):
        topic = Topic.objects.create(name='Тема уже загруженной')
        batch = self.create_batch()
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(batch, user=self.teacher)
        draft = batch.drafts.get()
        draft.refresh_from_db()
        original = draft.text_latex
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('textbook_import_review', args=[batch.pk, draft.pk])
        response = self.client.get(url)
        self.assertContains(response, 'только для просмотра')
        self.assertNotContains(response, 'Сохранить и дальше')
        response = self.client.post(url, {
            'external_id': draft.external_id,
            'source_number': draft.source_number,
            'text_latex': 'Подменённое условие $x=0$.',
            'subitems': json.dumps(draft.subitems),
            'author_answer_latex': draft.author_answer_latex,
            'author_solution_latex': draft.author_solution_latex,
            'status': TextbookTaskDraft.STATUS_REVIEW,
        })
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.text_latex, original)
        self.assertEqual(draft.status, TextbookTaskDraft.STATUS_IMPORTED)

    def test_another_editor_cannot_extend_owned_collection(self):
        topic = Topic.objects.create(name='Тема владельца')
        first = self.create_batch()
        first.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(first, user=self.teacher)

        other = make_teacher('teacher2')
        second = create_batch_from_bundle(
            bundle(external_id='1.2.38', source_number='38'),
            user=other, title='Чужая партия',
            source_title='Тестовый задачник', source_author='Автор')
        second.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        with self.assertRaisesMessage(TextbookImportError,
                                      'другому редактору'):
            commit_batch(second, user=other)
        leaf = Collection.objects.get(
            source_path=['Алгебра', 'Квадратные уравнения'])
        self.assertEqual(leaf.worksheet.items.count(), 1)

    def test_different_collection_keys_keep_same_named_leaves_separate(self):
        topic = Topic.objects.create(name='Тема одинаковых названий')
        payload = bundle(source_path=['Раздел', 'Упражнения'])
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            collection_key='alg.other', text_latex='Вторая задача.'))
        batch = self.create_batch(payload)
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)

        commit_batch(batch, user=self.teacher)

        leaves = Collection.objects.filter(is_published=True)
        self.assertEqual(leaves.count(), 2)
        self.assertEqual(
            set(leaves.values_list('locator', flat=True)),
            {'key:alg.quadratic', 'key:alg.other'})
        self.assertEqual(
            sorted(collection.worksheet.items.count()
                   for collection in leaves), [1, 1])

    def test_collection_key_survives_display_title_change(self):
        topic = Topic.objects.create(name='Тема переименования')
        first = self.create_batch(bundle(
            source_path=['Старое название'],
            collection_title='Старое название'))
        first.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(first, user=self.teacher)

        second = self.create_batch(bundle(
            external_id='1.2.38', source_number='38',
            source_path=['Новое название'],
            collection_title='Новое название', text_latex='Вторая задача.'))
        second.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(second, user=self.teacher)

        leaves = Collection.objects.filter(is_published=True)
        self.assertEqual(leaves.count(), 1)
        leaf = leaves.get(locator='key:alg.quadratic')
        self.assertEqual(leaf.source_path, ['Новое название'])
        self.assertEqual(leaf.worksheet.title, 'Новое название')
        self.assertEqual(leaf.worksheet.items.count(), 2)

    def test_review_pages_render(self):
        batch = self.create_batch()
        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        self.assertContains(detail, '1.2.37')
        review = self.client.get(reverse(
            'textbook_import_review', args=[batch.pk, batch.drafts.get().pk]))
        self.assertContains(review, 'Авторский ответ')
        self.assertContains(review, 'Предпросмотр авторского ответа')
        self.assertContains(review, 'Предпросмотр авторского решения')
        self.assertContains(review, 'import-status-button')
        self.assertContains(review, 'Результат проверки')
        self.assertContains(review, 'value="needs_review" checked')
        self.assertContains(review, 'Сохранить и дальше')
        self.assertContains(review, 'import-source-edit')
        self.assertContains(review, 'Править исходник ответа')
        self.assertContains(
            review,
            'только выбирают статус. Запись — после «Сохранить»')
        self.assertContains(review, 'import-review-actions')
        self.assertContains(review, 'import-wrap-math')
        self.assertContains(review, '$…$')
        self.assertNotContains(review, 'Взять решение у ключа')
        self.assertNotContains(review, 'Кандидаты с решениями')
        self.assertContains(detail, '>Импорт задачников<')

    def test_review_shows_two_column_subitems_in_letter_order(self):
        batch = self.create_batch(bundle(
            text_latex='Сравните значения выражений:',
            subitems=[
                {'label': 'а', 'text_latex': r'$\sqrt{47}$ и $\sqrt{7}$'},
                {'label': 'в', 'text_latex': r'$0,8^{-2}$ и $0,8^{-1}$'},
                {'label': 'б', 'text_latex': r'$2^{1/2}$ и $4^{1/4}$'},
                {'label': 'г', 'text_latex': r'$(1,06)^{-5}$ и 1'},
            ],
            author_answer_latex='', author_solution_latex='',
        ))
        draft = batch.drafts.get()
        draft.subitems = [
            {'label': 'а', 'text_latex': r'$\sqrt{47}$ и $\sqrt{7}$',
             'author_answer_latex': '', 'author_solution_latex': ''},
            {'label': 'в', 'text_latex': r'$0,8^{-2}$ и $0,8^{-1}$',
             'author_answer_latex': '', 'author_solution_latex': ''},
            {'label': 'б', 'text_latex': r'$2^{1/2}$ и $4^{1/4}$',
             'author_answer_latex': '', 'author_solution_latex': ''},
            {'label': 'г', 'text_latex': r'$(1,06)^{-5}$ и 1',
             'author_answer_latex': '', 'author_solution_latex': ''},
        ]
        draft.save(update_fields=['subitems'])
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]))
        labels = [
            item['label'] for item in response.context['review_subitems']]
        self.assertEqual(labels, ['а', 'б', 'в', 'г'])
        html = response.content.decode()
        self.assertLess(html.index('Подпункт а'), html.index('Подпункт б'))
        self.assertLess(html.index('Подпункт б'), html.index('Подпункт в'))

    def test_review_edits_subitem_author_materials_and_uses_topic_picker(self):
        first_topic = Topic.objects.create(name='Первая тема')
        second_topic = Topic.objects.create(name='Вторая тема')
        batch = self.create_batch(bundle(
            subitems=[{
                'label': 'а',
                'text_latex': 'Первый подпункт.',
                'author_answer_latex': 'Старый ответ.',
                'author_solution_latex': 'Старое решение.',
            }],
            author_answer_latex='', author_solution_latex='',
        ))
        draft = batch.drafts.get()
        draft.topic = first_topic
        draft.save(update_fields=['topic'])
        self.client.login(username='teacher1', password='pass12345')
        url = reverse(
            'textbook_import_review', args=[batch.pk, draft.pk])

        response = self.client.get(url)

        self.assertContains(response, 'name="subitem_author_answer_0"')
        self.assertContains(response, 'name="subitem_text_0"')
        self.assertContains(response, 'name="subitem_label_0"')
        self.assertContains(response, 'Старый ответ.')
        self.assertContains(response, 'name="subitem_author_solution_0"')
        self.assertContains(response, 'Старое решение.')
        self.assertContains(response, 'Править исходник условия')
        self.assertContains(response, 'Править исходник ответа')
        self.assertContains(response, 'Править исходник решения')
        self.assertContains(response, 'name="author_answer_latex"')
        self.assertContains(response, 'name="author_solution_latex"')
        self.assertContains(response, 'data-tax-picker')
        self.assertContains(response, 'data-single="0"')
        self.assertContains(response, 'data-primary="1"')
        self.assertContains(response, 'Тема: код или название')
        self.assertIn(str(first_topic.pk), response.context['selected_json'])

        response = self.client.post(url, {
            'external_id': draft.external_id,
            'source_number': draft.source_number,
            'text_latex': draft.text_latex,
            'subitems': json.dumps(draft.subitems),
            'subitem_author_answer_0': 'Новый ответ.',
            'subitem_author_solution_0': 'Новое решение.',
            'author_answer_latex': 'Общий материал.',
            'author_solution_latex': 'Общий материал.',
            'topic': str(second_topic.pk),
            'status': TextbookTaskDraft.STATUS_REVIEW,
        })

        self.assertRedirects(response, reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.topic, second_topic)
        self.assertEqual(draft.topic_ids, [second_topic.pk])
        self.assertEqual(
            draft.subitems[0]['author_answer_latex'], 'Новый ответ.')
        self.assertEqual(
            draft.subitems[0]['author_solution_latex'], 'Новое решение.')
        self.assertEqual(draft.author_answer_latex, 'Общий материал.')
        self.assertEqual(draft.author_solution_latex, 'Общий материал.')

    def test_review_rejects_invalid_subitem_mask_without_text_editors(self):
        batch = self.create_batch(bundle(
            subitems=[{
                'label': 'а', 'text_latex': 'Первый подпункт.',
                'author_answer_latex': '$1$',
            }],
            author_answer_latex='', author_solution_latex=''))
        draft = batch.drafts.get()
        original_mask = draft.subitems[0]['answer_mask']
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': draft.text_latex,
                'subitems': json.dumps(draft.subitems),
                'subitem_author_answer_0': '$1$',
                'subitem_answer_mask_0': '{{number: не число}}',
                'subitem_author_solution_0': '',
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Некорректная маска')
        draft.refresh_from_db()
        self.assertEqual(draft.subitems[0]['answer_mask'], original_mask)

    def test_commit_preserves_common_author_material_with_subitems(self):
        topic = Topic.objects.create(name='Тема подпунктов')
        batch = self.create_batch(bundle(
            subitems=[{
                'label': 'а', 'text_latex': 'Первый подпункт.',
                'author_answer_latex': 'Ответ подпункта.',
                'author_solution_latex': 'Решение подпункта.',
            }],
            author_answer_latex='Общий ответ.',
            author_solution_latex='Общее решение.',
        ))
        batch.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)

        commit_batch(batch, user=self.teacher)

        task = Task.objects.get()
        self.assertEqual(task.author_answer_latex, 'Общий ответ.')
        self.assertEqual(task.author_solution_latex, 'Общее решение.')
        subitem = task.subitems.get()
        self.assertEqual(subitem.author_answer_latex, 'Ответ подпункта.')
        self.assertEqual(subitem.author_solution_latex, 'Решение подпункта.')

    def test_review_saves_subitem_text_and_author_in_one_request(self):
        batch = self.create_batch(bundle(subitems=[
            {
                'label': 'а', 'text_latex': 'Первый подпункт.',
                'author_solution_latex': 'Первое решение.',
            },
            {
                'label': 'б', 'text_latex': 'Второй подпункт.',
                'author_solution_latex': 'Второе решение.',
            },
        ]))
        draft = batch.drafts.get()
        original = [dict(item) for item in draft.subitems]
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': 'Общее условие.',
                'subitems': json.dumps(original),
                'subitem_label_0': 'а',
                'subitem_text_0': 'Новый первый подпункт.',
                'subitem_author_answer_0': '',
                'subitem_author_solution_0': 'Изменённое первое решение.',
                'subitem_label_1': 'б',
                'subitem_text_1': 'Второй подпункт.',
                'subitem_author_answer_1': '',
                'subitem_author_solution_1': 'Второе решение.',
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.text_latex, 'Общее условие.')
        self.assertEqual(draft.subitems[0]['text_latex'], 'Новый первый подпункт.')
        self.assertEqual(
            draft.subitems[0]['author_solution_latex'],
            'Изменённое первое решение.')
        self.assertEqual(draft.subitems[1]['label'], 'б')

    def test_review_json_can_delete_and_add_subitems(self):
        batch = self.create_batch(bundle(subitems=[
            {
                'label': 'а', 'text_latex': 'Первый подпункт.',
                'author_solution_latex': 'Первое решение.',
            },
            {
                'label': 'б', 'text_latex': 'Второй подпункт.',
                'author_solution_latex': 'Второе решение.',
            },
        ]))
        draft = batch.drafts.get()
        original = [dict(item) for item in draft.subitems]
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': draft.text_latex,
                'subitems': json.dumps([original[1]]),
                'subitem_label_0': 'а',
                'subitem_text_0': 'Первый подпункт.',
                'subitem_author_answer_0': '',
                'subitem_author_solution_0': 'Первое решение.',
                'subitem_label_1': 'б',
                'subitem_text_1': 'Второй подпункт.',
                'subitem_author_answer_1': '',
                'subitem_author_solution_1': 'Второе решение.',
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual([item['label'] for item in draft.subitems], ['б'])
        self.assertEqual(draft.subitems[0]['text_latex'], 'Второй подпункт.')

        added = {
            'label': 'в', 'text_latex': 'Новый третий.',
            'author_answer_latex': '', 'author_solution_latex': '',
        }
        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': draft.text_latex,
                'subitems': json.dumps([original[1], added]),
                'subitem_label_0': 'б',
                'subitem_text_0': 'Второй подпункт.',
                'subitem_author_answer_0': '',
                'subitem_author_solution_0': 'Второе решение.',
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(
            [item['label'] for item in draft.subitems], ['б', 'в'])
        self.assertEqual(draft.subitems[1]['text_latex'], 'Новый третий.')

    def test_review_keeps_author_fields_on_json_reorder_by_label(self):
        batch = self.create_batch(bundle(subitems=[
            {
                'label': 'а', 'text_latex': 'Первый подпункт.',
                'author_solution_latex': 'Первое решение.',
            },
            {
                'label': 'б', 'text_latex': 'Второй подпункт.',
                'author_solution_latex': 'Второе решение.',
            },
        ]))
        draft = batch.drafts.get()
        original = [dict(item) for item in draft.subitems]
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': draft.text_latex,
                'subitems': json.dumps(list(reversed(original))),
                'subitem_author_answer_0': '',
                'subitem_author_solution_0': 'Изменённое первое решение.',
                'subitem_author_answer_1': '',
                'subitem_author_solution_1': 'Второе решение.',
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        by_label = {item['label']: item for item in draft.subitems}
        self.assertEqual(by_label['а']['text_latex'], 'Первый подпункт.')
        self.assertEqual(
            by_label['а']['author_solution_latex'],
            'Изменённое первое решение.')
        self.assertEqual(by_label['б']['text_latex'], 'Второй подпункт.')

    def test_review_allows_structure_edit_when_author_fields_unchanged(self):
        batch = self.create_batch(bundle(subitems=[
            {
                'label': 'а', 'text_latex': 'Первый подпункт.',
                'author_solution_latex': 'Первое решение.',
            },
            {
                'label': 'б', 'text_latex': 'Второй подпункт.',
                'author_solution_latex': 'Второе решение.',
            },
        ]))
        draft = batch.drafts.get()
        original = [dict(item) for item in draft.subitems]
        reordered = list(reversed(original))
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': draft.text_latex,
                'subitems': json.dumps(reordered),
                'subitem_author_answer_0': '',
                'subitem_author_solution_0': 'Первое решение.',
                'subitem_author_answer_1': '',
                'subitem_author_solution_1': 'Второе решение.',
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(
            [item['label'] for item in draft.subitems], ['а', 'б'])
        by_label = {item['label']: item for item in draft.subitems}
        self.assertEqual(by_label['а']['author_solution_latex'], 'Первое решение.')
        self.assertEqual(by_label['б']['author_solution_latex'], 'Второе решение.')

    def test_collection_preview_assigns_topic_to_one_source_section(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            text_latex='Вторая задача раздела.'))
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='2.1.1', source_number='1',
            source_path=['Геометрия', 'Треугольники'],
            collection_key='geometry.triangles',
            collection_title='Треугольники',
            text_latex='Задача другого раздела.'))
        batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Квадратные уравнения')
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))

        groups = response.context['collection_groups']
        algebra = next(
            group for group in groups
            if group['collection_key'] == 'alg.quadratic')
        self.assertEqual(algebra['count'], 2)
        self.assertContains(response, 'Предпросмотр подборок и массовая тема')
        self.assertContains(response, 'Все задачи')
        self.assertContains(response, 'data-single="0"')
        self.assertContains(response, 'data-primary="1"')

        response = self.client.post(reverse(
            'textbook_import_assign_section_topic', args=[batch.pk]), {
                'section': algebra['token'],
                'topic': str(topic.pk),
            })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            batch.drafts.filter(
                collection_key='alg.quadratic', topic=topic).count(), 2)

        self.assertNotEqual(
            batch.drafts.get(collection_key='geometry.triangles').topic_id,
            topic.pk)

        response = self.client.post(reverse(
            'textbook_import_assign_section_topic', args=[batch.pk]), {
                'section': algebra['token'], 'topic': 'not-a-number',
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            batch.drafts.filter(
                collection_key='alg.quadratic', topic=topic).count(), 2)

        replacement = Topic.objects.create(name='Другая тема')
        batch.status = TextbookImportBatch.STATUS_IMPORTED
        batch.save(update_fields=['status'])
        response = self.client.post(reverse(
            'textbook_import_assign_section_topic', args=[batch.pk]), {
                'section': algebra['token'],
                'topic': str(replacement.pk),
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            batch.drafts.filter(
                collection_key='alg.quadratic', topic=topic).count(), 2)

    def test_collection_preview_can_assign_topic_to_chapter_or_subsection(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='2.1.1', source_number='1',
            source_path=['Алгебра', 'Линейные уравнения'],
            collection_key='alg.linear',
            collection_title='Линейные уравнения',
            text_latex='Решите линейное уравнение.'))
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='3.1.1', source_number='1',
            source_path=['Геометрия', 'Треугольники'],
            collection_key='geometry.triangles',
            collection_title='Треугольники',
            text_latex='Задача о треугольнике.'))
        batch = self.create_batch(payload)
        topic = Topic.objects.create(name='Тема главы')
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))
        groups = response.context['collection_groups']
        chapter = next(
            group for group in groups
            if group['path'] == ['Алгебра'] and not group['is_leaf'])
        subsection = next(
            group for group in groups
            if group['collection_key'] == 'alg.quadratic')
        self.assertEqual(chapter['count'], 2)
        self.assertEqual(chapter['level_label'], 'Глава целиком')
        self.assertTrue(subsection['is_leaf'])
        self.assertContains(response, f'section={chapter["token"]}')
        self.assertContains(response, f'section={subsection["token"]}')
        self.assertContains(response, 'Алгебра')
        self.assertContains(response, 'Квадратные уравнения')
        self.assertNotContains(response, 'Показать подборку')
        self.assertNotContains(response, '<optgroup')

        response = self.client.post(reverse(
            'textbook_import_assign_section_topic', args=[batch.pk]), {
                'section': chapter['token'], 'topic': str(topic.pk),
            })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            batch.drafts.filter(source_path__0='Алгебра', topic=topic).count(),
            2)
        self.assertNotEqual(
            batch.drafts.get(collection_key='geometry.triangles').topic_id,
            topic.pk)

    def test_import_list_previews_subitems_and_author_material_presence(self):
        batch = self.create_batch(bundle(
            text_latex='Вычислите:',
            subitems=[{
                'label': 'а', 'text_latex': '$1+1$',
                'author_answer_latex': '2',
                'author_solution_latex': '$1+1=2$.',
            }, {
                'label': 'б', 'text_latex': '$2+2$',
            }],
            author_answer_latex='', author_solution_latex='',
        ))
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))

        self.assertContains(response, 'Задание и подпункты')
        self.assertContains(response, '>Отв.<')
        self.assertContains(response, '>Реш.<')
        self.assertContains(response, 'import-status-review')
        self.assertContains(response, 'title="Не проверена"')
        self.assertContains(response, '$1+1$', html=False)
        self.assertContains(response, 'title="1/2"')
        html = response.content.decode()
        self.assertEqual(html.count('Вычислите:'), 1)
        self.assertEqual(html.count('$1+1$'), 1)
        self.assertNotIn('class="ws-num"', html)
        self.assertNotIn('а) а)', html)
        self.assertContains(response, 'id="toggle-import-draft-answers"')
        self.assertContains(response, 'ответы и решения')
        self.assertContains(response, 'answer-box')
        self.assertContains(response, 'class="ws-answers" hidden')
        self.assertContains(response, 'а)&nbsp;')
        self.assertContains(response, 'Авторское решение:')
        self.assertNotContains(response, 'class="show-answers"')
        self.assertNotContains(response, '— ответ:')

    def test_import_repairs_answer_glued_after_closed_math(self):
        batch = self.create_batch(bundle(
            text_latex='Вычислите:',
            subitems=[{
                'label': 'а',
                'text_latex': r'\(\cos\alpha=\frac{3}{5}\)',
                'author_answer_latex': (
                    r'\(\sin\alpha=-\frac{4}{5};\operatorname{tg}\alpha='
                    r'-\frac{4}{3}\); \(\operatorname{ctg}\alpha='
                    r'-\frac{3}{4};\) б) \(\cos\alpha=-\frac{4}{5}\)'),
                'author_solution_latex': '',
            }, {
                'label': 'б',
                'text_latex': r'\(\operatorname{tg}\alpha=-\frac{3}{4}\)',
                'author_answer_latex': '',
                'author_solution_latex': '',
            }],
            author_answer_latex='', author_solution_latex='',
        ))
        draft = batch.drafts.get()
        self.assertNotIn('б)', draft.subitems[0]['author_answer_latex'])
        self.assertIn(r'\cos\alpha', draft.subitems[1]['author_answer_latex'])

    def test_collection_preview_is_paginated_separately(self):
        payload = bundle()
        payload['tasks'] = [dict(
            payload['tasks'][0], external_id=f'1.2.{number}',
            source_number=str(number), text_latex=f'Задача {number}.')
            for number in range(1, 52)]
        batch = self.create_batch(payload)
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))

        self.assertIsNone(response.context['selected_group'])
        page = response.context['page']
        self.assertEqual(page.paginator.count, 51)
        self.assertEqual(len(page.object_list), 50)
        self.assertEqual(page.paginator.num_pages, 2)
        self.assertContains(response, 'class="pagination"')
        self.assertContains(response, 'page=2')
        self.assertContains(response, 'Назад')
        self.assertContains(response, 'Следующая')
        self.assertNotContains(response, '→')

        group = next(
            item for item in response.context['collection_groups']
            if item['is_leaf'])
        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'section': group['token'], 'page': 2,
        })
        self.assertEqual(len(response.context['page'].object_list), 1)

    def test_user_guide_explains_statuses_and_commit_boundary(self):
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(reverse('textbook_import_help'))

        self.assertContains(response, 'Когда задачи попадают в базу')
        self.assertContains(response, 'Не проверена')
        self.assertContains(response, 'Одобрена')
        self.assertContains(response, 'Конфликт')
        self.assertContains(response, 'Пропущена')
        self.assertContains(response, 'Импортировано')
        self.assertContains(response, 'Подборки')
        self.assertContains(response, 'одной транзакции')

    def test_batch_detail_counts_all_drafts_by_status(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38'))
        batch = self.create_batch(payload)
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))

        self.assertContains(response, 'Не проверена (2)')

    def test_review_rejects_structurally_invalid_subitems(self):
        batch = self.create_batch()
        draft = batch.drafts.get()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]), {
                'external_id': draft.external_id,
                'source_number': draft.source_number,
                'text_latex': draft.text_latex,
                'subitems': '{}',
                'author_answer_latex': draft.author_answer_latex,
                'author_solution_latex': draft.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_APPROVED,
            })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'должно быть массивом')
        draft.refresh_from_db()
        self.assertEqual(draft.status, TextbookTaskDraft.STATUS_REVIEW)

    def test_review_rejects_duplicate_external_id(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38'))
        batch = self.create_batch(payload)
        first, second = list(batch.drafts.all())
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse(
            'textbook_import_review', args=[batch.pk, second.pk]), {
                'external_id': first.external_id,
                'source_number': second.source_number,
                'text_latex': second.text_latex,
                'subitems': '[]',
                'author_answer_latex': second.author_answer_latex,
                'author_solution_latex': second.author_solution_latex,
                'status': TextbookTaskDraft.STATUS_REVIEW,
            })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'уже существует в этой партии')
        second.refresh_from_db()
        self.assertEqual(second.external_id, '1.2.38')

    def test_review_saves_manual_solution_without_copy_key(self):
        batch = self.create_batch(bundle(author_solution_latex=''))
        draft = batch.drafts.get()
        self.client.login(username='teacher1', password='pass12345')
        url = reverse(
            'textbook_import_review', args=[batch.pk, draft.pk])
        response = self.client.post(url, {
            'external_id': draft.external_id,
            'source_number': draft.source_number,
            'text_latex': draft.text_latex,
            'subitems': '[]',
            'author_answer_latex': draft.author_answer_latex,
            'author_solution_latex': 'Решение исправлено вручную.',
            'status': TextbookTaskDraft.STATUS_REVIEW,
        })
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(
            draft.author_solution_latex, 'Решение исправлено вручную.')

    def test_image_zip_unblocks_commit_and_creates_task_image(self):
        topic = Topic.objects.create(name='Тема с рисунком')
        batch = self.create_batch(bundle(images=['figure-1.png']))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('folder/figure-1.png', TINY_PNG)
        archive.seek(0)
        stored = attach_image_archive(
            batch, SimpleUploadedFile('pics.zip', archive.read()))
        self.assertEqual(stored, 1)
        draft = batch.drafts.get()
        self.assertEqual(draft.images, ['figure-1.png'])
        self.assertFalse(any(
            'Требуется загрузить' in item for item in draft.warnings))
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.topic = topic
        draft.save()
        commit_batch(batch, user=self.teacher)
        self.assertEqual(TaskImage.objects.count(), 1)
        self.assertIn('figure-1', TaskImage.objects.get().filename)

    def test_image_stem_keeps_decimal_source_number(self):
        self.assertEqual(
            normalize_image_stem('merzlyak9-fig-11.7'),
            'merzlyak9-fig-11.7')
        self.assertEqual(
            normalize_image_stem('folder/merzlyak9-fig-11.7.png'),
            'merzlyak9-fig-11.7')

        batch = self.create_batch(bundle(images=['merzlyak9-fig-11.7']))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('merzlyak9-fig-11.7.png', TINY_PNG)
        archive.seek(0)

        stored = attach_image_archive(
            batch, SimpleUploadedFile('pics.zip', archive.read()))

        self.assertEqual(stored, 1)
        draft = batch.drafts.get()
        self.assertEqual(draft.unmatched_images(), [])
        self.assertFalse(any(
            'Требуется загрузить' in item for item in draft.warnings))

    def test_create_batch_collects_ocr_images_from_subitem_solution(self):
        payload = bundle(
            images=[],
            author_answer_latex='',
            author_solution_latex='',
            subitems=[{
                'label': 'а',
                'text_latex': r'\(y=x\)',
                'author_answer_latex': 'см. рис. 25',
                'author_solution_latex': (
                    r'$\includegraphics[alt={}$,$max width=\textwidth]{fig-25'
                    '\n'
                    r'\caption{$Рис. 25.}'
                ),
            }],
        )
        batch = self.create_batch(payload)
        draft = batch.drafts.get()
        self.assertEqual(draft.images, ['fig-25'])
        self.assertIn(r'\taskpic{1}', draft.subitems[0]['author_answer_latex'])
        self.assertIn('см. рис.', draft.subitems[0]['author_answer_latex'])
        self.assertNotIn('рис. 25', draft.subitems[0]['author_answer_latex'])
        self.assertNotIn(
            'includegraphics', draft.subitems[0]['author_solution_latex'])
        self.assertTrue(any(
            'Требуется загрузить' in item for item in draft.warnings))

    def test_image_zip_skips_macos_appledouble_and_matches_ocr_stem(self):
        payload = bundle(
            images=[],
            author_answer_latex='',
            author_solution_latex='',
            subitems=[{
                'label': 'а',
                'text_latex': 'график',
                'author_answer_latex': '',
                'author_solution_latex': (
                    r'$\includegraphics[alt={}$,$max width=\textwidth]{fig-25'),
            }],
        )
        batch = self.create_batch(payload)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('fig-25.jpg', TINY_PNG)
            zf.writestr('._fig-25.jpg', TINY_PNG)
            zf.writestr('__MACOSX/._fig-25.jpg', TINY_PNG)
        archive.seek(0)
        stored = attach_image_archive(
            batch, SimpleUploadedFile('pics.zip', archive.read()))
        self.assertEqual(stored, 1)
        self.assertEqual(batch.assets.count(), 1)
        self.assertEqual(batch.assets.get().stem, 'fig-25')
        draft = batch.drafts.get()
        self.assertEqual(draft.images, ['fig-25'])
        self.assertFalse(any(
            'Требуется загрузить' in item for item in draft.warnings))

    def test_sync_recovers_images_on_already_saved_draft(self):
        batch = self.create_batch(bundle(images=[]))
        draft = batch.drafts.get()
        draft.subitems = [{
            'label': 'б',
            'text_latex': r'\(y=|x|\)',
            'author_answer_latex': 'см. рис. 26',
            'author_solution_latex': (
                r'\begin{figure}[h]'
                r'$\includegraphics[alt={}$,$max width=\textwidth]{uuid-fig-26'
                r'\caption{$Рис. 26.}'
                r'\end{figure}'
            ),
        }]
        draft.author_answer_latex = ''
        draft.author_solution_latex = ''
        draft.save()
        self.assertEqual(sync_batch_draft_images(batch), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.images, ['uuid-fig-26'])
        self.assertIn(r'\taskpic{1}', draft.subitems[0]['author_answer_latex'])
        self.assertIn('см. рис.', draft.subitems[0]['author_answer_latex'])
        self.assertNotIn(r'\begin{figure}', draft.subitems[0]['author_solution_latex'])

    def test_sync_splits_ziv_answer_leak_and_places_each_figure(self):
        payload = bundle(
            external_id='sr/10/v7/3',
            source_number='3',
            images=[],
            author_answer_latex='',
            author_solution_latex='',
            subitems=[
                {
                    'label': 'а',
                    'text_latex': r'\(y=x\)',
                    'author_answer_latex': 'см. рис. 25',
                    'author_solution_latex': '',
                },
                {
                    'label': 'б',
                    'text_latex': r'\(y=|x|\)',
                    'author_answer_latex': (
                        r'см. рис. 26. 4. Если \(a>0\), то 2 решения.'),
                    'author_solution_latex': (
                        r'\taskpic{fig-25}' + '\n' + r'\taskpic{fig-26}'),
                },
            ])
        payload['profile'] = 'ziv'
        payload['tasks'].append(dict(
            payload['tasks'][0],
            external_id='sr/10/v7/4',
            source_number='4',
            text_latex=r'Сколько решений?',
            subitems=[],
            author_answer_latex='',
            author_solution_latex='',
            images=[]))
        batch = self.create_batch(payload)
        graph = batch.drafts.get(external_id='sr/10/v7/3')
        following = batch.drafts.get(external_id='sr/10/v7/4')
        self.assertEqual(graph.images, ['fig-25', 'fig-26'])
        self.assertIn(r'\taskpic{1}', graph.subitems[0]['author_answer_latex'])
        self.assertIn(r'\taskpic{2}', graph.subitems[1]['author_answer_latex'])
        self.assertNotIn('Если', graph.subitems[1]['author_answer_latex'])
        self.assertIn('Если', following.author_answer_latex)
        self.assertIn('2 решения', following.author_answer_latex)
        self.assertNotIn(r'\taskpic', following.author_answer_latex)

    def test_image_zip_rejects_duplicate_stems(self):
        batch = self.create_batch(bundle(images=['plot.png']))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('chapter1/plot.png', TINY_PNG)
            zf.writestr('chapter2/plot.jpg', TINY_PNG)
        archive.seek(0)
        with self.assertRaises(TextbookImportError) as ctx:
            attach_image_archive(
                batch, SimpleUploadedFile('pics.zip', archive.read()))
        self.assertIn('plot', str(ctx.exception))
        self.assertEqual(batch.assets.count(), 0)
        draft = batch.drafts.get()
        self.assertTrue(any(
            'Требуется загрузить' in item for item in draft.warnings))

    def test_commit_section_imports_only_approved_topic(self):
        topic_a = Topic.objects.create(name='Тема раздела A')
        payload = bundle(
            source_path=['Глава', 'Тема A'],
            collection_key='sec.a',
            collection_title='Тема A',
            topic_original='Тема A')
        payload['tasks'].append(dict(
            payload['tasks'][0],
            external_id='1.2.38',
            source_number='38',
            text_latex='Задача другого раздела.',
            source_path=['Глава', 'Тема B'],
            collection_key='sec.b',
            collection_title='Тема B',
            topic_original='Тема B'))
        batch = self.create_batch(payload)
        first = batch.drafts.get(external_id='1.2.37')
        second = batch.drafts.get(external_id='1.2.38')
        first.status = TextbookTaskDraft.STATUS_APPROVED
        first.topic = topic_a
        first.save()

        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        groups = detail.context['collection_groups']
        section = next(
            group for group in groups
            if group['is_leaf'] and group['path'][-1] == 'Тема A')
        response = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]),
            {'section': section['token']})
        self.assertTrue(response.context['selected_group']['can_commit'])
        self.assertContains(response, 'Загрузить тему в каталог')

        response = self.client.post(
            reverse('textbook_import_commit_section', args=[batch.pk]),
            {'section': section['token']})
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(first.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(second.status, TextbookTaskDraft.STATUS_REVIEW)
        self.assertEqual(batch.status, TextbookImportBatch.STATUS_REVIEW)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(first.imported_task_id, Task.objects.get().pk)

    def test_commit_section_imports_approved_while_siblings_wait(self):
        topic = Topic.objects.create(name='Тема раздела')
        payload = bundle(
            source_path=['Глава', 'Тема A'],
            collection_key='sec.a',
            collection_title='Тема A')
        payload['tasks'].append(dict(
            payload['tasks'][0],
            external_id='1.2.38',
            source_number='38',
            text_latex='Сосед по тому же разделу.',
            source_path=['Глава', 'Тема A'],
            collection_key='sec.a',
            collection_title='Тема A'))
        batch = self.create_batch(payload)
        first = batch.drafts.get(external_id='1.2.37')
        first.status = TextbookTaskDraft.STATUS_APPROVED
        first.topic = topic
        first.save()

        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        section = next(
            group for group in detail.context['collection_groups']
            if group['is_leaf'] and group['path'][-1] == 'Тема A')
        response = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]),
            {'section': section['token']})
        self.assertTrue(response.context['selected_group']['can_commit'])
        self.assertEqual(response.context['selected_group']['open_count'], 1)
        self.assertContains(response, 'Загрузить тему в каталог')

        response = self.client.post(
            reverse('textbook_import_commit_section', args=[batch.pk]),
            {'section': section['token']})
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second = batch.drafts.get(external_id='1.2.38')
        batch.refresh_from_db()
        self.assertEqual(first.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(second.status, TextbookTaskDraft.STATUS_REVIEW)
        self.assertEqual(batch.status, TextbookImportBatch.STATUS_REVIEW)
        self.assertEqual(Task.objects.count(), 1)

    def test_import_strips_subitem_marker_and_trailing_space(self):
        batch = self.create_batch(bundle(
            text_latex='Найдите значение выражения: Найдите значение выражения:\\\\',
            subitems=[{
                'label': 'а',
                'text_latex': r'а) $564\cdot645$ ?\\',
            }],
        ))
        draft = batch.drafts.get()
        self.assertEqual(draft.text_latex, 'Найдите значение выражения:')
        self.assertEqual(draft.subitems[0]['text_latex'], r'$564\cdot645$?')

    def test_import_heals_ocr_linebreak_and_spaced_hyphen(self):
        batch = self.create_batch(bundle(
            text_latex=(
                r'Последовательность задана формулой '
                r'\(c_{n}=-3 n^{2}+\) \(+7 n+4\). '
                r'\(a_{n}\) - арифметическая прогрессия.'
            ),
        ))
        draft = batch.drafts.get()
        self.assertEqual(
            draft.text_latex,
            r'Последовательность задана формулой '
            r'\(c_{n}=-3 n^{2}+7 n+4\). '
            r'\(a_{n}\) — арифметическая прогрессия.',
        )

    def test_bad_image_zip_rolls_back_new_batch(self):
        self.client.login(username='teacher1', password='pass12345')
        upload = SimpleUploadedFile(
            'import.json', json.dumps(bundle()).encode(),
            content_type='application/json')
        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Партия с плохим ZIP', 'source_title': 'Задачник',
            'source_author': 'Автор',
            'input_kind': 'json', 'bundle': upload,
            'images_zip': SimpleUploadedFile(
                'pics.zip', b'not-a-zip', content_type='application/zip'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Нужен ZIP')
        self.assertEqual(TextbookImportBatch.objects.count(), 0)
        self.assertEqual(TextbookTaskDraft.objects.count(), 0)

    def test_exact_topic_alias_is_assigned_automatically(self):
        topic = Topic.objects.get(code='ALG.03.03')
        batch = self.create_batch()
        draft = batch.drafts.get()
        self.assertEqual(draft.topic_id, topic.pk)
        self.assertEqual(draft.topic_candidates[0]['reason'], 'exact-alias')

    def test_oge_numbered_heading_still_auto_assigns_alias(self):
        topic = Topic.objects.get(code='ARI.03')
        batch = self.create_batch(bundle(
            external_id='6.1',
            source_path=['№6. Дроби', 'Прототипы'],
            topic_original='Дроби',
            collection_key='oge/06/proto',
            collection_title='№6. Дроби — прототипы',
        ))
        draft = batch.drafts.get()
        self.assertEqual(draft.topic_id, topic.pk)
        self.assertEqual(draft.topic_candidates[0]['reason'], 'exact-alias')
        self.assertEqual(draft.topic_candidates[0]['score'], 1.0)

    def test_fuzzy_topic_candidate_is_not_auto_assigned(self):
        Topic.objects.create(
            code='ALG.09.99', name='Текстовые задачи на пароходы')
        candidates = match_topic_candidates(
            ['Текстовые задачи на пароход'])
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]['reason'], 'fuzzy-name')
        batch = self.create_batch(bundle(
            source_path=['Текстовые задачи на пароход'],
            topic_original='Текстовые задачи на пароход',
            collection_key='other',
        ))
        self.assertIsNone(batch.drafts.get().topic_id)

    def test_ziv_v12_headings_auto_assign_new_topics(self):
        cases = [
            (['Контрольные работы', 'Основные тригонометрические тождества',
              'Вариант 1'], 'ALG.02.18'),
            (['Самостоятельные работы', 'Степень с рациональным показателем',
              'Вариант 2'], 'ALG.02.16'),
            (['Контрольные работы', 'Радианная мера угла', 'Вариант 1'],
             'ALG.05.17'),
            (['Самостоятельные работы',
              'Область определения функции. Возрастание и убывание функции',
              'Вариант 3'], 'ALG.05.01'),
            (['Контрольные работы', 'Неравенства, содержащие степень',
              'Вариант 1'], 'ALG.04.11'),
            (['Контрольные работы', 'Системы уравнений второй степени',
              'Вариант 1'], 'ALG.03.15'),
        ]
        for source_path, code in cases:
            topic = Topic.objects.get(code=code)
            batch = self.create_batch(bundle(
                external_id=code,
                source_path=source_path,
                topic_original=source_path[-1],
                collection_key=code.lower(),
                collection_title=source_path[1],
            ))
            draft = batch.drafts.get()
            self.assertEqual(draft.topic_id, topic.pk, source_path)
            self.assertIn(
                draft.topic_candidates[0]['reason'],
                {'exact-alias', 'exact-name'})

    def test_merzlyak_geometry_sections_auto_assign_topics(self):
        cases = [
            ('§ 1. Синус, косинус, тангенс и котангенс угла от 0° до 180°',
             'GEO.02.07'),
            ('§ 2. Теорема косинусов', 'GEO.02.07'),
            ('§ 3. Теорема синусов', 'GEO.02.07'),
            ('§ 4. Решение треугольников', 'GEO.02.07'),
            ('§ 5. Формулы для нахождения площади треугольника',
             'GEO.02.08'),
            ('§ 6. Правильные многоугольники и их свойства', 'GEO.03.05'),
            ('§ 7. Длина окружности. Площадь круга', 'GEO.04.06'),
            ('§ 8. Расстояние между двумя точками с данными координатами. '
             'Деление отрезка в данном отношении', 'GEO.06.01'),
            ('§ 9. Уравнение фигуры', 'GEO.06.03'),
            ('§ 10. Общее уравнение прямой', 'GEO.06.02'),
            ('§ 11. Уравнение прямой с угловым коэффициентом. Уравнение '
             'прямой, проходящей через две данные точки', 'GEO.06.02'),
            ('§ 12. Метод координат', 'GEO.06.06'),
            ('§ 13. Понятие вектора', 'GEO.06.04'),
            ('§ 14. Координаты вектора', 'GEO.06.05'),
            ('§ 15. Сложение и вычитание векторов', 'GEO.06.04'),
            ('§ 16. Умножение вектора на число. Применение векторов '
             'к решению задач', 'GEO.06.04'),
            ('§ 17. Скалярное произведение векторов', 'GEO.06.05'),
            ('§ 18. Преобразование (отображение) фигур', 'GEO.05.06'),
            ('§ 19. Движение. Параллельный перенос', 'GEO.05.02'),
            ('§ 20. Осевая симметрия', 'GEO.05.01'),
            ('§ 21. Центральная симметрия', 'GEO.05.01'),
            ('§ 22. Поворот', 'GEO.05.02'),
            ('§ 23. Гомотетия. Подобие фигур', 'GEO.05.03'),
        ]
        for index, (heading, code) in enumerate(cases, 1):
            topic = Topic.objects.get(code=code)
            batch = self.create_batch(bundle(
                external_id=f'merzlyak-topic-{index}',
                source_path=['Геометрия 9', heading],
                topic_original=heading,
                collection_key=f'merzlyak/{index}',
                collection_title=heading,
            ))
            draft = batch.drafts.get()
            self.assertEqual(draft.topic_id, topic.pk, heading)
            self.assertEqual(
                draft.topic_candidates[0]['reason'], 'exact-alias', heading)

    def test_merzlyak_geometry_mixed_sections_get_broad_topics(self):
        cases = [
            (['Глава 6. Начальные сведения по стереометрии',
              '§ 24. Прямая призма. Пирамида'], 'GEO.09'),
            (['Глава 6. Начальные сведения по стереометрии',
              '§ 25. Цилиндр. Конус. Шар'], 'GEO.10'),
            (['§ 26. Упражнения для повторения курса планиметрии',
              '1. Треугольники'], 'GEO.02'),
            (['§ 26. Упражнения для повторения курса планиметрии',
              '2. Четырехугольники. Многоугольники'], 'GEO.03'),
            (['§ 26. Упражнения для повторения курса планиметрии',
              '3. Окружность и её элементы'], 'GEO.04'),
            (['§ 26. Упражнения для повторения курса планиметрии',
              '4. Декартовы координаты. Векторы'], 'GEO.06'),
            (['§ 26. Упражнения для повторения курса планиметрии',
              '5. Геометрические преобразования'], 'GEO.05'),
        ]
        for index, (source_path, code) in enumerate(cases, 1):
            topic = Topic.objects.get(code=code)
            batch = self.create_batch(bundle(
                external_id=f'merzlyak-mixed-{index}',
                source_path=source_path,
                topic_original=source_path[-1],
                collection_key=f'merzlyak/mixed/{index}',
                collection_title=source_path[-1],
            ))
            draft = batch.drafts.get()
            self.assertEqual(draft.topic_id, topic.pk, source_path)
            self.assertEqual(draft.topic_ids, [topic.pk], source_path)
            self.assertEqual(
                draft.topic_candidates[0]['reason'], 'exact-alias',
                source_path)

    def test_ziv_variant_path_auto_assigns_section_topic(self):
        topic = Topic.objects.get(code='ALG.06.02')
        batch = self.create_batch(bundle(
            source_path=[
                'Контрольные работы', 'Арифметическая прогрессия',
                'Вариант 1',
            ],
            topic_original='Вариант 1',
            collection_key='kr/04/v1',
            collection_title='Арифметическая прогрессия',
            text_latex='Найдите сумму первых десяти членов.',
        ))
        draft = batch.drafts.get()
        self.assertEqual(draft.topic_id, topic.pk)
        self.assertIn(
            draft.topic_candidates[0]['reason'],
            {'exact-alias', 'exact-name'})

    def test_section_button_assigns_suggested_topic_without_picker(self):
        topic = Topic.objects.get(code='ALG.06.02')
        batch = self.create_batch(bundle(
            source_path=[
                'Контрольные работы', 'Арифметическая прогрессия',
                'Вариант 1',
            ],
            topic_original='Вариант 1',
            collection_key='kr/04/v1',
            collection_title='Арифметическая прогрессия',
            text_latex='Найдите сумму первых десяти членов.',
        ))
        draft = batch.drafts.get()
        draft.topic = None
        draft.save(update_fields=['topic'])
        self.assertEqual(suggested_topic_for_drafts(batch.drafts.all()), topic)

        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))
        token = next(
            item['token'] for item in response.context['collection_groups']
            if item['is_leaf'])
        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'section': token,
        })
        self.assertEqual(response.context['suggested_topic'], topic)
        self.assertContains(response, f'Назначить тему: {topic}')
        self.assertContains(response, 'tax-picker-compact')
        self.assertContains(response, reverse(
            'textbook_import_quick_topic', args=[batch.pk, draft.pk]))

        response = self.client.post(reverse(
            'textbook_import_assign_section_topic', args=[batch.pk]), {
                'section': token,
            })
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.topic_id, topic.pk)

    def test_quick_topic_updates_one_draft(self):
        batch = self.create_batch(bundle(
            source_path=['Геометрия', 'Треугольники'],
            topic_original='Треугольники',
            collection_key='geometry.triangles',
            collection_title='Треугольники',
            text_latex='Найдите сторону треугольника.',
        ))
        draft = batch.drafts.get()
        draft.topic = None
        draft.save(update_fields=['topic'])
        topic = Topic.objects.get(code='GEO.02')
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(
            reverse('textbook_import_quick_topic',
                    args=[batch.pk, draft.pk]),
            {'topic': str(topic.pk)},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        draft.refresh_from_db()
        self.assertEqual(draft.topic_id, topic.pk)
        self.assertEqual(draft.topic_ids, [topic.pk])

    def test_quick_topic_saves_multiple_topics(self):
        batch = self.create_batch(bundle(
            source_path=['Геометрия', 'Треугольники'],
            topic_original='Треугольники',
            collection_key='geometry.triangles',
            collection_title='Треугольники',
            text_latex='Найдите сторону треугольника.',
        ))
        draft = batch.drafts.get()
        first = Topic.objects.create(name='Первая тема импорта')
        second = Topic.objects.create(name='Вторая тема импорта')
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(
            reverse('textbook_import_quick_topic',
                    args=[batch.pk, draft.pk]),
            {'topics': [str(first.pk), str(second.pk)],
             'primary_topic': str(second.pk),
             'topics_submitted': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.topic_id, second.pk)
        self.assertEqual(draft.topic_ids, [second.pk, first.pk])

        page = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        self.assertIn(str(first.pk), page.context['page'][0].taxonomy_json)
        self.assertIn(str(second.pk), page.context['page'][0].taxonomy_json)
        self.assertContains(page, 'data-chip-full="1"')
        self.assertContains(page, 'Увер.')
        self.assertNotContains(page, '>Замечания<')

    def test_commit_writes_all_draft_topics(self):
        primary = Topic.objects.create(name='Основная импорта')
        extra = Topic.objects.create(name='Дополнительная импорта')
        batch = self.create_batch()
        draft = batch.drafts.get()
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        set_draft_topics(draft, [primary.pk, extra.pk], primary.pk)
        draft.save(update_fields=['status'])
        commit_batch(batch, user=self.teacher)
        task = Task.objects.get()
        self.assertEqual(
            set(task.topics.values_list('pk', flat=True)),
            {primary.pk, extra.pk})
        self.assertEqual(
            task.topic_links.get(role=TaskTopic.ROLE_PRIMARY).topic_id,
            primary.pk)
        leaf = Collection.objects.get(
            source_path=['Алгебра', 'Квадратные уравнения'])
        self.assertEqual(
            set(leaf.worksheet.topics.values_list('pk', flat=True)),
            {primary.pk, extra.pk})

    def test_upload_parses_ziv_profile_explicitly(self):
        self.client.login(username='teacher1', password='pass12345')
        source = r"""
\section*{Самостоятельные работы}
\section*{1. Числовые неравенства}
Вариант 1
\begin{itemize}
  \item[1.] Сравните дроби.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{1. Числовые неравенства}
Вариант 1
\begin{itemize}
  \item[1.] $1<2$.
\end{itemize}
"""
        upload = SimpleUploadedFile(
            'ziv.tex', source.encode(), content_type='text/plain')
        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Зив', 'source_title': 'Зив-8',
            'input_kind': 'answers_end', 'profile': 'ziv',
            'tasks_tex': upload,
        })
        self.assertEqual(response.status_code, 302)
        draft = TextbookTaskDraft.objects.get()
        self.assertEqual(draft.batch.profile, 'ziv')
        self.assertEqual(draft.external_id, 'sr/01/v1/1')
        self.assertEqual(draft.author_answer_latex, '$1<2$')

    def test_import_strips_section_and_answer_dots(self):
        batch = self.create_batch(bundle(
            source_path=['Чётные и нечётные функции.'],
            collection_title='Чётные и нечётные функции.',
            author_answer_latex='четная.',
        ))
        draft = batch.drafts.get()
        self.assertEqual(draft.source_path, ['Чётные и нечётные функции'])
        self.assertEqual(draft.collection_title, 'Чётные и нечётные функции')
        self.assertEqual(draft.author_answer_latex, 'четная')

        sentence = self.create_batch(bundle(
            external_id='1.2.38',
            author_answer_latex='Нет корней.',
        ))
        self.assertEqual(
            sentence.drafts.get().author_answer_latex, 'Нет корней.')

    def test_status_filter_keeps_selected_section(self):
        batch = self.create_batch()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))
        self.assertFalse(response.context['selected_section'])
        self.assertIsNone(response.context['selected_group'])
        token = next(
            item['token'] for item in response.context['collection_groups']
            if item['is_leaf'])
        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'section': token,
        })
        self.assertContains(response, f'status=needs_review')
        self.assertContains(response, f'section={token}')
        self.assertNotContains(response, '<optgroup')
        self.assertContains(response, 'import-bulk-form')
        self.assertContains(response, 'name="ids"')

    def test_section_and_status_filter_one_table(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            text_latex='Вторая задача раздела.'))
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='2.1.1', source_number='1',
            source_path=['Геометрия', 'Треугольники'],
            collection_key='geometry.triangles',
            collection_title='Треугольники',
            text_latex='Задача другого раздела.'))
        batch = self.create_batch(payload)
        first = batch.drafts.get(external_id='1.2.37')
        first.status = TextbookTaskDraft.STATUS_APPROVED
        first.save(update_fields=['status'])
        self.client.login(username='teacher1', password='pass12345')

        landing = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))
        self.assertEqual(landing.context['page'].paginator.count, 3)
        self.assertContains(landing, 'Все задачи')
        self.assertContains(landing, 'import-drafts-wrap')
        self.assertContains(landing, 'import-toolbar')
        self.assertContains(landing, 'import-section-part')
        self.assertContains(landing, 'import-section-path')
        self.assertContains(landing, 'Раздел + темы')
        self.assertContains(landing, 'col-meta')
        self.assertNotContains(landing, '>№<')
        self.assertContains(landing, 'import-key-status')
        algebra = next(
            group for group in landing.context['collection_groups']
            if group['collection_key'] == 'alg.quadratic')

        section = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'section': algebra['token'],
        })
        ids = {draft.external_id for draft in section.context['page']}
        self.assertEqual(ids, {'1.2.37', '1.2.38'})
        self.assertContains(section, 'import-section-current')
        self.assertContains(section, 'Все задачи')
        self.assertContains(section, 'status=approved')
        self.assertContains(section, f'section={algebra["token"]}')

        filtered = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'section': algebra['token'],
                'status': TextbookTaskDraft.STATUS_APPROVED,
        })
        self.assertEqual(
            [draft.external_id for draft in filtered.context['page']],
            ['1.2.37'])
        self.assertNotIn('section=', filtered.context['all_sections_href'])
        self.assertIn('status=', filtered.context['all_sections_href'])
        self.assertTrue(filtered.context['all_sections_href'].startswith('?'))
        self.assertTrue(landing.context['all_sections_href'].startswith('?'))

        cleared = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'status': TextbookTaskDraft.STATUS_APPROVED,
        })
        self.assertFalse(cleared.context['selected_section'])
        self.assertEqual(
            [draft.external_id for draft in cleared.context['page']],
            ['1.2.37'])

    def test_answers_none_filter_keeps_section_and_status(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            author_answer_latex='', text_latex='Без ответа.'))
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.39', source_number='39',
            author_answer_latex='',
            subitems=[{
                'label': 'а',
                'text_latex': 'Подпункт',
                'author_answer_latex': '1',
            }],
            text_latex='Ответ только в подпункте.'))
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='2.1.1', source_number='1',
            source_path=['Геометрия', 'Треугольники'],
            collection_key='geometry.triangles',
            collection_title='Треугольники',
            author_answer_latex='',
            text_latex='Пустая задача другого раздела.'))
        batch = self.create_batch(payload)
        empty = batch.drafts.get(external_id='1.2.38')
        empty.status = TextbookTaskDraft.STATUS_APPROVED
        empty.save(update_fields=['status'])
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('textbook_import_detail', args=[batch.pk])

        landing = self.client.get(url)
        self.assertEqual(landing.context['missing_answer_count'], 2)
        self.assertContains(landing, 'Без ответов (2)')
        self.assertContains(landing, 'btn btn-secondary')
        self.assertIn('answers=none', landing.context['missing_answers_href'])
        self.assertNotIn('answers=', landing.context['all_drafts_href'])

        algebra = next(
            group for group in landing.context['collection_groups']
            if group['collection_key'] == 'alg.quadratic')
        filtered = self.client.get(url, {
            'section': algebra['token'],
            'status': TextbookTaskDraft.STATUS_APPROVED,
            'answers': 'none',
            'page': '3',
        })
        self.assertEqual(filtered.context['answers_filter'], 'none')
        self.assertEqual(filtered.context['missing_answer_count'], 1)
        self.assertEqual(
            [draft.external_id for draft in filtered.context['page']],
            ['1.2.38'])
        self.assertContains(filtered, 'Без ответов (1)')
        self.assertContains(filtered, 'is-current')
        self.assertNotIn('answers=', filtered.context['missing_answers_href'])
        self.assertIn('status=approved', filtered.context['missing_answers_href'])
        self.assertIn(
            f'section={algebra["token"]}',
            filtered.context['missing_answers_href'])
        self.assertNotIn('page=', filtered.context['missing_answers_href'])
        self.assertIn('answers=none', filtered.context['list_query'])
        self.assertNotIn('page=', filtered.context['list_query'])
        self.assertNotIn('answers=', filtered.context['all_drafts_href'])
        self.assertIn(
            f'section={algebra["token"]}',
            filtered.context['all_drafts_href'])
        approved_tab = next(
            tab for tab in filtered.context['status_tabs']
            if tab['value'] == TextbookTaskDraft.STATUS_APPROVED)
        self.assertIn('answers=none', approved_tab['href'])
        self.assertTrue(approved_tab['current'])

    def test_bulk_skips_and_deletes_selected_drafts(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            text_latex='Вторая задача.'))
        batch = self.create_batch(payload)
        first, second = list(batch.drafts.order_by('external_id'))
        topic = Topic.objects.create(name='Массовая тема')
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('textbook_import_bulk', args=[batch.pk])

        response = self.client.post(url, {
            'ids': [str(first.pk)],
            'skip': '1',
            'next': reverse('textbook_import_detail', args=[batch.pk]),
        })
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        self.assertEqual(first.status, TextbookTaskDraft.STATUS_SKIPPED)

        response = self.client.post(url, {
            'ids': [str(second.pk)],
            'topic': str(topic.pk),
            'next': reverse('textbook_import_detail', args=[batch.pk]),
        })
        self.assertEqual(response.status_code, 302)
        second.refresh_from_db()
        self.assertIn(topic.pk, second.topic_ids)
        kept_primary = second.topic_id
        self.assertIsNotNone(kept_primary)

        extra = Topic.objects.create(name='Вторая массовая тема')
        response = self.client.post(url, {
            'ids': [str(second.pk)],
            'topics': [str(extra.pk)],
            'next': reverse('textbook_import_detail', args=[batch.pk]),
        })
        self.assertEqual(response.status_code, 302)
        second.refresh_from_db()
        self.assertEqual(second.topic_id, kept_primary)
        self.assertEqual(
            set(second.topic_ids),
            {kept_primary, topic.pk, extra.pk})

        response = self.client.post(url, {
            'ids': [str(second.pk)],
            'delete': '1',
            'next': reverse('textbook_import_detail', args=[batch.pk]),
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(batch.drafts.filter(pk=second.pk).exists())
        self.assertTrue(batch.drafts.filter(pk=first.pk).exists())

    def test_bulk_updates_status_of_selected_drafts(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            text_latex='Вторая задача.'))
        batch = self.create_batch(payload)
        first, second = list(batch.drafts.order_by('external_id'))
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('textbook_import_bulk', args=[batch.pk])
        next_url = reverse('textbook_import_detail', args=[batch.pk])

        response = self.client.get(next_url)
        self.assertContains(response, 'name="status" value="approved"')
        self.assertContains(response, 'name="status" value="conflict"')

        response = self.client.post(url, {
            'ids': [str(first.pk), str(second.pk)],
            'status': TextbookTaskDraft.STATUS_APPROVED,
            'next': next_url,
        })
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, TextbookTaskDraft.STATUS_APPROVED)
        self.assertEqual(second.status, TextbookTaskDraft.STATUS_APPROVED)

        self.client.post(url, {
            'ids': [str(second.pk)],
            'status': TextbookTaskDraft.STATUS_CONFLICT,
            'next': next_url,
        })
        second.refresh_from_db()
        self.assertEqual(second.status, TextbookTaskDraft.STATUS_CONFLICT)

        self.client.post(url, {
            'ids': [str(first.pk)],
            'status': TextbookTaskDraft.STATUS_REVIEW,
            'next': next_url,
        })
        first.refresh_from_db()
        self.assertEqual(first.status, TextbookTaskDraft.STATUS_REVIEW)

    def test_bulk_ignores_already_imported_drafts(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38',
            text_latex='Вторая задача.'))
        batch = self.create_batch(payload)
        imported, open_draft = list(batch.drafts.order_by('external_id'))
        imported.status = TextbookTaskDraft.STATUS_IMPORTED
        imported.save(update_fields=['status'])
        topic = Topic.objects.create(name='После импорта')
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('textbook_import_bulk', args=[batch.pk])
        next_url = reverse('textbook_import_detail', args=[batch.pk])

        response = self.client.get(next_url)
        self.assertNotContains(
            response, f'name="ids" value="{imported.pk}"')
        self.assertContains(
            response, f'name="ids" value="{open_draft.pk}"')

        self.client.post(url, {
            'ids': [str(imported.pk), str(open_draft.pk)],
            'skip': '1', 'next': next_url,
        })
        imported.refresh_from_db()
        open_draft.refresh_from_db()
        self.assertEqual(imported.status, TextbookTaskDraft.STATUS_IMPORTED)
        self.assertEqual(open_draft.status, TextbookTaskDraft.STATUS_SKIPPED)

        self.client.post(url, {
            'ids': [str(imported.pk)],
            'topic': str(topic.pk), 'next': next_url,
        })
        imported.refresh_from_db()
        self.assertNotEqual(imported.topic_id, topic.pk)

        self.client.post(url, {
            'ids': [str(imported.pk)],
            'delete': '1', 'next': next_url,
        })
        self.assertTrue(batch.drafts.filter(pk=imported.pk).exists())

    def test_review_save_stays_and_save_next_advances(self):
        payload = bundle()
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='1.2.38', source_number='38'))
        batch = self.create_batch(payload)
        first, second = list(batch.drafts.order_by('external_id'))
        self.client.login(username='teacher1', password='pass12345')
        url = reverse('textbook_import_review', args=[batch.pk, first.pk])
        form = {
            'external_id': first.external_id,
            'source_number': first.source_number,
            'text_latex': first.text_latex,
            'subitems': '[]',
            'author_answer_latex': first.author_answer_latex,
            'author_solution_latex': first.author_solution_latex,
            'status': TextbookTaskDraft.STATUS_REVIEW,
        }

        response = self.client.post(url, form)
        self.assertRedirects(response, reverse(
            'textbook_import_review', args=[batch.pk, first.pk]))

        response = self.client.post(url, {**form, 'save_next': '1'})
        self.assertRedirects(response, reverse(
            'textbook_import_review', args=[batch.pk, second.pk]))

    def test_repair_ziv_batch_splits_merged_variant_and_trims_heading(self):
        payload = {
            'schema_version': 1,
            'profile': 'ziv',
            'diagnostics': {},
            'tasks': [
                {
                    'external_id': 'kr/03/v3/1',
                    'source_number': '1',
                    'source_path': [
                        'Контрольные работы', 'Степенная функция', 'Вариант 3',
                    ],
                    'collection_key': 'kr/03/v3',
                    'collection_title': 'Степенная функция',
                    'topic_original': 'Степенная функция',
                    'text_latex': (
                        'Исследуйте функции на четность и нечетность:'),
                    'subitems': [
                        {'label': 'а',
                         'text_latex': r'\(f(x)=x^{4}-3 x^{2}+1\)'},
                        {'label': 'б', 'text_latex': '\n'.join([
                            r'\(f(x)=-2 x|x|+4 x^{3}\).',
                            r'\setcounter{enumi}{1}',
                            'Найдите области определения функций:',
                            r'а) \(f(x)=\sqrt{x}\).',
                            r'Вариант 4',
                            'Исследуйте функции на четность и нечетность:',
                            r'а) \(f(x)=3 x^{3}\).',
                        ])},
                    ],
                    'author_answer_latex': '',
                    'author_solution_latex': '',
                    'confidence': 1,
                    'warnings': [],
                },
                {
                    'external_id': 'kr/03/v2/1',
                    'source_number': '1',
                    'source_path': [
                        'Контрольные работы', 'Степенная функция', 'Вариант 2',
                    ],
                    'collection_key': 'kr/03/v2',
                    'collection_title': 'Степенная функция',
                    'topic_original': 'Степенная функция',
                    'text_latex': 'Уже существующая задача варианта 2.',
                    'subitems': [],
                    'author_answer_latex': '',
                    'author_solution_latex': '',
                    'confidence': 1,
                    'warnings': [],
                },
                {
                    'external_id': 'sr/02/v0/5',
                    'source_number': '5',
                    'source_path': [
                        'Самостоятельные работы',
                        'Уравнения, сводящиеся к апгебраическим',
                        'Вариант 0',
                    ],
                    'collection_key': 'sr/02/v0',
                    'collection_title': 'Уравнения, сводящиеся к апгебраическим',
                    'topic_original': 'Уравнения, сводящиеся к апгебраическим',
                    'text_latex': '\n'.join([
                        r'\(x^{2}=1\).',
                        r'Вариант 2\\',
                        r'Решите уравнения 1-5:',
                        r'1.~\(x^{2}=4\).',
                    ]),
                    'subitems': [],
                    'author_answer_latex': '',
                    'author_solution_latex': '',
                    'confidence': 1,
                    'warnings': [],
                },
                {
                    'external_id': 'kr/03/v1/4',
                    'source_number': '4',
                    'source_path': [
                        'Контрольные работы', 'Степенная функция', 'Вариант 1',
                    ],
                    'collection_key': 'kr/03/v1',
                    'collection_title': 'Степенная функция',
                    'topic_original': 'Степенная функция',
                    'text_latex': (
                        r'Решите уравнение \(x=1\).' '\nВариант 2'),
                    'subitems': [],
                    'author_answer_latex': '',
                    'author_solution_latex': '',
                    'confidence': 1,
                    'warnings': [],
                },
            ],
        }
        batch = self.create_batch(payload)
        stats = batch.diagnostics.get('ziv_leak_repair') or {}
        first = batch.drafts.get(external_id='kr/03/v3/1')
        joined = first.text_latex + ''.join(
            item['text_latex'] for item in first.subitems)
        self.assertIn('четность', first.text_latex)
        self.assertNotIn('Вариант 4', joined)
        self.assertNotIn('Найдите области', joined)
        self.assertTrue(batch.drafts.filter(external_id='kr/03/v3/2').exists())
        self.assertTrue(batch.drafts.filter(external_id='kr/03/v4/1').exists())
        existing = batch.drafts.get(external_id='kr/03/v2/1')
        self.assertEqual(
            existing.text_latex, 'Уже существующая задача варианта 2.')
        trimmed = batch.drafts.get(external_id='kr/03/v1/4')
        self.assertEqual(trimmed.text_latex, r'Решите уравнение \(x=1\).')
        self.assertIn('kr/03/v3/2', stats['created'])
        self.assertIn('kr/03/v1/4', stats['trimmed'])
        unlabeled = batch.drafts.get(external_id='sr/02/v0/5')
        self.assertIn(r'x^{2}=1', unlabeled.text_latex)
        self.assertNotIn('Вариант 2', unlabeled.text_latex)
        self.assertFalse(batch.drafts.filter(external_id='sr/02/v1/5').exists())
        self.assertTrue(batch.drafts.filter(external_id='sr/02/v2/1').exists())
        batch.refresh_from_db()
        self.assertIn('ziv_uneven_variant_topics', batch.diagnostics)
        again = repair_ziv_batch_leaks(batch)
        self.assertEqual(again['created'], [])
        # Выделенные задачи стоят сразу за источником, а не в конце партии.
        order = list(batch.drafts.values_list('external_id', flat=True))
        self.assertLess(order.index('kr/03/v3/1'), order.index('kr/03/v3/2'))
        self.assertLess(order.index('kr/03/v3/2'), order.index('kr/03/v2/1'))
        self.assertLess(order.index('kr/03/v4/1'), order.index('kr/03/v2/1'))
        self.assertLess(order.index('sr/02/v2/1'), order.index('kr/03/v1/4'))

    def test_repair_ziv_batch_splits_solve_stem_stuck_to_graph(self):
        payload = {
            'schema_version': 1,
            'profile': 'ziv',
            'diagnostics': {},
            'tasks': [{
                'external_id': 'kr/03/v3/3',
                'source_number': '3',
                'source_path': [
                    'Контрольные работы', 'Степенная функция', 'Вариант 3',
                ],
                'collection_key': 'kr/03/v3',
                'collection_title': 'Степенная функция',
                'topic_original': 'Степенная функция',
                'text_latex': 'item Постройте графики функций:',
                'subitems': [
                    {'label': 'а', 'text_latex': r'\(y=\sqrt{x-1}\)'},
                    {'label': 'б', 'text_latex': '\n'.join([
                        r'\(y=\sqrt{x+1}-2\).',
                        r'Найдите промежутки, на которых \(y(x)>0\).',
                        r'Решите уравнения:',
                        r'а) \(\sqrt{x+2}=x\).',
                    ])},
                ],
                'author_answer_latex': '',
                'author_solution_latex': '',
                'confidence': 1,
                'warnings': [],
            }],
        }
        batch = self.create_batch(payload)
        stats = batch.diagnostics.get('ziv_leak_repair') or {}
        graph = batch.drafts.get(external_id='kr/03/v3/3')
        joined = graph.text_latex + ''.join(
            item['text_latex'] for item in graph.subitems)
        self.assertTrue(graph.text_latex.startswith('Постройте'))
        self.assertNotIn('Решите уравнения', joined)
        self.assertIn('kr/03/v3/4', stats['created'])
        solve = batch.drafts.get(external_id='kr/03/v3/4')
        self.assertIn('Решите уравнения', solve.text_latex)

    def test_ziv_detail_shows_variant_length_summary(self):
        tasks = []
        for variant, n in ((1, 4), (2, 4), (3, 3), (4, 2)):
            for number in range(1, n + 1):
                tasks.append({
                    'external_id': f'kr/03/v{variant}/{number}',
                    'source_number': str(number),
                    'source_path': [
                        'Контрольные работы', 'Степенная функция',
                        f'Вариант {variant}',
                    ],
                    'collection_key': f'kr/03/v{variant}',
                    'collection_title': 'Степенная функция',
                    'topic_original': 'Степенная функция',
                    'text_latex': f'Задача {variant}.{number}.',
                    'subitems': [],
                    'author_answer_latex': '',
                    'author_solution_latex': '',
                    'confidence': 1,
                    'warnings': [],
                })
        batch = self.create_batch({
            'schema_version': 1,
            'profile': 'ziv',
            'diagnostics': {},
            'tasks': tasks,
        })
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        self.assertContains(response, 'Число задач по вариантам')
        self.assertContains(response, 'Степенная функция')
        self.assertContains(response, '4 / 4 / 3 / 2')
        self.assertContains(response, 'import-ziv-parity-uneven')
        groups = response.context['collection_groups']
        chapter = next(
            group for group in groups
            if group['path'] == ['Контрольные работы'] and not group['is_leaf'])
        topic = next(
            group for group in groups
            if group['path'] == [
                'Контрольные работы', 'Степенная функция']
            and not group['is_leaf'])
        self.assertContains(response, f'section={chapter["token"]}')
        self.assertContains(response, f'section={topic["token"]}')
        self.assertNotContains(response, 'Показать подборку')
        response = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]),
            {'section': topic['token']})
        self.assertEqual(response.context['selected_section'], topic['token'])
        self.assertEqual(
            response.context['selected_group']['path'],
            ['Контрольные работы', 'Степенная функция'])

    def test_ziv_parser_splits_answer_after_closed_formula(self):
        source = r"""
\section*{Контрольные работы}
\section*{4. Тригонометрические функции}
Вариант 2
\begin{itemize}
  \item[2.] Вычислите значения тригонометрических функций, если:
а) \(\displaystyle \cos \alpha=\frac{3}{5} ; \frac{3 \pi}{2}<\alpha<2 \pi\)
б) \(\displaystyle \operatorname{tg} \alpha=-\frac{3}{4} ; \frac{\pi}{2}<\alpha<\pi\)
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{4. Тригонометрические функции}
Вариант 2. 2. \(\displaystyle \sin \alpha=-\frac{4}{5} ; \operatorname{tg} \alpha=-\frac{4}{3}\); \(\displaystyle \operatorname{ctg} \alpha=-\frac{3}{4} ;\) б) \(\displaystyle \cos \alpha=-\frac{4}{5} ; \sin \alpha=\frac{3}{5} ; \operatorname{ctg} \alpha=-\frac{4}{3}\)
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == 'kr/04/v2/2')
        answers = [item.author_answer_latex for item in task.subitems]
        self.assertEqual([item.label for item in task.subitems], ['а', 'б'])
        self.assertIn(r'\sin \alpha', answers[0])
        self.assertNotIn('б)', answers[0])
        self.assertIn(r'\cos \alpha', answers[1])
        self.assertEqual(task.author_answer_latex, '')

    def test_ziv_parser_moves_leaked_next_task_number(self):
        source = r"""
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 3
\begin{itemize}
  \item[1.] Решите системы:
а) \(x+y=5\)
б) \(x-y=1\)
  \item[2.] Решите уравнение.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 3. 1. а) $(2;3)$ б) $(-1,75;-3);\left(-\frac{7}{6};-2\right)$.2 .$\left\{\frac{5}{4};3\right\}$.
"""
        tasks, _ = parse_ziv(source)
        first = next(item for item in tasks if item.external_id == 'kr/01/v3/1')
        second = next(item for item in tasks if item.external_id == 'kr/01/v3/2')
        glued = ' '.join(
            [first.author_answer_latex]
            + [item.author_answer_latex for item in first.subitems])
        self.assertNotIn('.2 .', glued)
        self.assertIn(r'\frac{5}{4}', second.author_answer_latex)

    def test_review_wraps_bare_set_answer(self):
        batch = self.create_batch(bundle(
            text_latex=r'Решите уравнение \(x^{3}+3 x^{2}-4=0\).',
            author_answer_latex=r'\{-2;1\}',
            author_solution_latex='',
        ))
        draft = batch.drafts.get()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]))
        self.assertContains(response, r'$\{-2;1\}$', html=False)
