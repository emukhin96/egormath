"""Сверка партии: сводка разделов, порядок книги, маски и пакеты правок."""

import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import TextbookTaskDraft, Topic
from .shabunin_parser import prepare_shabunin_text
from .test_textbook_import import bundle, make_teacher
from .textbook_import import DEFERRED_MASK_WARNING, create_batch_from_bundle
from .textbook_patches import (TextbookPatchError, apply_draft_patch,
                               batch_rows, build_draft_patch)

CHAPTER = 'Глава 1. Элементы математической логики'
PARAGRAPH = '§ 1. Высказывания и операции над ними'


def row(external_id, level, **extra):
    data = {
        'external_id': external_id,
        'source_number': external_id,
        'source_path': [CHAPTER, PARAGRAPH, level],
        'collection_key': '/'.join([CHAPTER, PARAGRAPH, level]),
        'collection_title': CHAPTER,
        'topic_original': PARAGRAPH,
        'text_latex': f'Задача {external_id}.',
        'subitems': [],
        'author_answer_latex': '$4$',
        'confidence': 1,
        'warnings': [],
    }
    data.update(extra)
    return data


class ReviewToolsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        payload = bundle()
        # Книжный порядок: I.2 раньше I.10, хотя строкой «I.10» < «I.2».
        payload['tasks'] = [
            row('I.2', 'Первый уровень'),
            row('I.10', 'Первый уровень'),
            row('I.11', 'Второй уровень', author_answer_latex='$7$'),
        ]
        self.batch = create_batch_from_bundle(
            payload, user=self.teacher, title='Партия',
            source_title='Шабунин')

    def test_drafts_and_review_neighbours_follow_book_order(self):
        self.assertEqual(
            list(self.batch.drafts.values_list('external_id', flat=True)),
            ['I.2', 'I.10', 'I.11'])
        first = self.batch.drafts.get(external_id='I.2')
        response = self.client.get(
            reverse('textbook_import_review', args=[self.batch.pk, first.pk]))
        self.assertEqual(response.context['following'].external_id, 'I.10')
        self.assertIsNone(response.context['previous'])

    def test_transfer_package_keeps_book_order(self):
        from .textbook_transfer import serialize_batch
        self.assertEqual(
            [row['external_id'] for row in serialize_batch(self.batch)['drafts']],
            ['I.2', 'I.10', 'I.11'])

    def test_levels_are_links_inside_paragraph_row(self):
        response = self.client.get(
            reverse('textbook_import_detail', args=[self.batch.pk]))
        rows = response.context['section_nav']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], PARAGRAPH)
        self.assertEqual(rows[0]['count'], 3)
        self.assertEqual([(level['title'], level['count']) for level in rows[0]['levels']],
                         [('Первый уровень', 2), ('Второй уровень', 1)])
        self.assertContains(response, 'import-section-levels')

    def test_review_button_saves_and_fills_pending_masks(self):
        draft = self.batch.drafts.get(external_id='I.2')
        draft.answer_mask = ''
        draft.warnings = [DEFERRED_MASK_WARNING]
        draft.save()
        review = reverse('textbook_import_review', args=[self.batch.pk, draft.pk])
        response = self.client.get(review)
        self.assertContains(response, 'Сохранить и подобрать маски')
        data = {name: field.value() or '' for name, field in
                ((name, response.context['form'][name])
                 for name in response.context['form'].fields)}
        data.update({'author_answer_latex': '$5$', 'prepare_masks': '1',
                     'topic_ids': [], 'topic': ''})
        response = self.client.post(review, {k: v for k, v in data.items() if v is not None})
        self.assertRedirects(response, review)
        draft.refresh_from_db()
        # Подбор идёт по ответу, сохранённому в том же запросе.
        self.assertEqual(draft.author_answer_latex, '$5$')
        self.assertEqual(draft.answer_mask, '{{number: 5}}')
        self.assertNotIn(DEFERRED_MASK_WARNING, draft.warnings)
        response = self.client.get(review)
        self.assertContains(response, 'Как увидит ученик')
        self.assertNotContains(response, 'Сохранить и подобрать маски')

    def test_prepare_masks_keeps_fresh_image_warning(self):
        draft = self.batch.drafts.get(external_id='I.2')
        draft.answer_mask = ''
        draft.warnings = [DEFERRED_MASK_WARNING]
        draft.save()
        review = reverse('textbook_import_review', args=[self.batch.pk, draft.pk])
        form = self.client.get(review).context['form']
        data = {name: form[name].value() or '' for name in form.fields}
        # Учитель сослался на рисунок, файла которого в партии нет.
        data.update({'text_latex': r'Задача I.2. \taskpic{fig9}',
                     'prepare_masks': '1', 'topic_ids': [], 'topic': ''})
        self.client.post(review, data)
        draft.refresh_from_db()
        self.assertEqual(draft.answer_mask, '{{number: 4}}')
        self.assertTrue(any('изображений' in w for w in draft.warnings), draft.warnings)

    def test_exam_draft_mask_is_left_to_exam_format(self):
        TextbookTaskDraft.objects.filter(batch=self.batch).update(
            answer_mask='', exam_item_codes=['EGE_1'])
        draft = self.batch.drafts.get(external_id='I.2')
        self.assertTrue(draft.masks_by_exam)
        self.assertTrue(draft.mask_summary['exam'])
        review = self.client.get(
            reverse('textbook_import_review', args=[self.batch.pk, draft.pk]))
        self.assertContains(review, 'ставится при загрузке по формату задания экзамена')
        self.assertContains(review, 'data-exam-codes="EGE_1"')
        detail = self.client.get(reverse('textbook_import_detail', args=[self.batch.pk]))
        self.assertContains(detail, 'по формату')

    def test_mask_draft_gets_exam_codes_and_numbers(self):
        with patch('assignments.checks.draft_mask', return_value='{{number: 4}}') as draft_mask:
            response = self.client.post(reverse('task_mask_draft'), {
                'answer': '$4$', 'condition': 'Найдите $x$.',
                'exam_codes': ['EGE_1', 'EGE_2'], 'source_number': 'I.2',
                'subitem_label': '3'})
        self.assertEqual(response.json()['mask'], '{{number: 4}}')
        draft_mask.assert_called_once_with(
            '$4$', 'Найдите $x$.', exam_codes=['EGE_1', 'EGE_2'],
            source_number='I.2', subitem_label='3')

    def test_migration_backfills_book_order_and_places_split_drafts(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module(
            'problems.migrations.0028_textbook_draft_position')
        split = TextbookTaskDraft.objects.create(
            batch=self.batch, external_id='I.3', source_number='I.3',
            text_latex='Выделенная задача.',
            warnings=[migration.SPLIT_WARNING])
        TextbookTaskDraft.objects.filter(batch=self.batch).update(position=0)
        migration.fill_positions(apps, None)
        self.assertEqual(
            list(self.batch.drafts.values_list('external_id', 'position')),
            [('I.2', 10), ('I.3', 11), ('I.10', 20), ('I.11', 30)])
        self.assertEqual(split.warnings, [migration.SPLIT_WARNING])

    def test_batch_button_prepares_unapproved_drafts(self):
        TextbookTaskDraft.objects.filter(batch=self.batch).update(
            answer_mask='', warnings=[DEFERRED_MASK_WARNING])
        detail = reverse('textbook_import_detail', args=[self.batch.pk])
        self.assertContains(self.client.get(detail), 'Подобрать маски (3)')
        with patch('problems.textbook_import.MASK_DRAFT_BUDGET_SECONDS', 0):
            response = self.client.post(
                reverse('textbook_import_prepare_masks', args=[self.batch.pk]))
        # Бюджет исчерпан после первой задачи: страница продолжает подбор.
        self.assertContains(response, 'Подбор масок ответов')
        self.client.post(reverse('textbook_import_prepare_masks', args=[self.batch.pk]))
        masks = dict(self.batch.drafts.values_list('external_id', 'answer_mask'))
        self.assertEqual(masks['I.11'], '{{number: 7}}')
        self.assertTrue(all(masks.values()))
        response = self.client.get(detail)
        self.assertNotContains(response, 'Подобрать маски (')
        self.assertContains(response, 'Маска ответа:')

    def test_review_edits_tags_and_list_shows_them(self):
        draft = self.batch.drafts.get(external_id='I.2')
        review = reverse('textbook_import_review', args=[self.batch.pk, draft.pk])
        form = self.client.get(review).context['form']
        data = {name: form[name].value() or '' for name in form.fields}
        data.update({'tags': 'задача с параметром,  построение графика, задача с параметром',
                     'topic_ids': [], 'topic': ''})
        self.client.post(review, data)
        draft.refresh_from_db()
        self.assertEqual(draft.tags, ['задача с параметром', 'построение графика'])
        self.assertContains(self.client.get(review),
                            'value="задача с параметром, построение графика"')
        detail = self.client.get(reverse('textbook_import_detail', args=[self.batch.pk]))
        self.assertContains(detail, '<span class="badge">задача с параметром</span>', html=True)
        # Метка с запятой в имени (от импортёра) не распадается при сохранении.
        draft.tags = ['задача с параметром', 'ОГЭ, часть 2']
        draft.save()
        form = self.client.get(review).context['form']
        self.assertEqual(form['tags'].value(), 'задача с параметром')
        data = {name: form[name].value() or '' for name in form.fields}
        data.update({'topic_ids': [], 'topic': ''})
        self.client.post(review, data)
        draft.refresh_from_db()
        self.assertEqual(draft.tags, ['задача с параметром', 'ОГЭ, часть 2'])

    def test_lone_set_brace_outside_math_is_wrapped(self):
        from .shabunin_parser import _wrap_lone_braces
        self.assertEqual(
            _wrap_lone_braces(r"$A \equiv \{$Число 54 делится на 2 \}"),
            r"$A \equiv \{$Число 54 делится на 2$\}$")
        self.assertEqual(_wrap_lone_braces(r"$\{1; 2\}$"), r"$\{1; 2\}$")

    def test_divisibility_becomes_compact_relation_macro(self):
        self.assertEqual(
            prepare_shabunin_text(r'1) $\left(2^{2 n+1}+1\right) \vdots 3$; ( $n^{p}-n$ ) ⋮ $p$'),
            r'1) $\left(2^{2 n+1}+1\right) \divby 3$; $(n^{p}-n) \divby p$')


class DraftPatchTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.topic_a = Topic.objects.create(name='Тема А', code='ZZ.01')
        self.topic_b = Topic.objects.create(name='Тема Б', code='ZZ.02')
        payload = bundle(topic_code='ZZ.01')
        payload['tasks'].append({**payload['tasks'][0], 'external_id': '1.2.38'})
        self.batch = create_batch_from_bundle(
            payload, user=self.teacher, title='Партия', source_title='Книга')
        self.baseline = batch_rows(self.batch)
        self.original = self.baseline['drafts'][0]

    def edit_and_build(self):
        draft = self.batch.drafts.get(external_id='1.2.37')
        draft.author_answer_latex = r'$x=\pm 2$'
        draft.answer_mask = '{{set: -2; 2}}'
        draft.topic = self.topic_b
        draft.topic_ids = [self.topic_b.pk]
        draft.source_number = '37а'
        draft.save()
        patch_data, untransferred = build_draft_patch(self.baseline, batch_rows(self.batch))
        self.assertEqual(untransferred, [('1.2.37', 'source_number')])
        # Возвращаем партию к исходному состоянию — как сервер до переноса.
        draft.author_answer_latex = self.original['author_answer_latex']
        draft.answer_mask = self.original['answer_mask']
        draft.topic = self.topic_a
        draft.topic_ids = [self.topic_a.pk]
        draft.source_number = self.original['source_number']
        draft.save()
        return json.loads(json.dumps(patch_data))

    def draft(self):
        return self.batch.drafts.get(external_id='1.2.37')

    def test_patch_has_only_changed_fields(self):
        patch_data = self.edit_and_build()
        self.assertEqual([row['external_id'] for row in patch_data['drafts']],
                         ['1.2.37'])
        self.assertEqual(set(patch_data['drafts'][0]['after']),
                         {'author_answer_latex', 'answer_mask',
                          'topic_code', 'topic_codes'})

    def test_dry_run_changes_nothing_and_apply_writes(self):
        patch_data = self.edit_and_build()
        report = apply_draft_patch(self.batch, patch_data)
        self.assertEqual(report['applied'], ['1.2.37'])
        self.assertEqual(self.draft().answer_mask, self.original['answer_mask'])
        apply_draft_patch(self.batch, patch_data, apply=True)
        draft = self.draft()
        self.assertEqual(draft.author_answer_latex, r'$x=\pm 2$')
        self.assertEqual(draft.answer_mask, '{{set: -2; 2}}')
        self.assertEqual(draft.topic_id, self.topic_b.pk)
        self.assertEqual(draft.topic_ids, [self.topic_b.pk])
        # Повторный запуск не считает свои же правки конфликтом.
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['already'], ['1.2.37'])
        self.assertEqual(report['skipped'], [])

    def test_later_teacher_edit_of_any_field_is_not_overwritten(self):
        patch_data = self.edit_and_build()
        draft = self.draft()
        # Учитель поправил поле, которого пакет не меняет.
        draft.text_latex = 'Решите $x^2=9$.'
        draft.save()
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['applied'], [])
        self.assertIn('text_latex', report['skipped'][0][1])
        self.assertEqual(self.draft().author_answer_latex,
                         self.original['author_answer_latex'])

    def test_approved_after_export_is_skipped(self):
        patch_data = self.edit_and_build()
        TextbookTaskDraft.objects.filter(batch=self.batch).update(
            status=TextbookTaskDraft.STATUS_APPROVED)
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertIn('статус', report['skipped'][0][1])

    def test_approved_at_export_returns_to_review(self):
        TextbookTaskDraft.objects.filter(batch=self.batch).update(
            status=TextbookTaskDraft.STATUS_APPROVED, reviewed_by=self.teacher)
        self.baseline = batch_rows(self.batch)
        self.original = self.baseline['drafts'][0]
        patch_data = self.edit_and_build()
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['reset'], ['1.2.37'])
        draft = self.draft()
        self.assertEqual(draft.status, TextbookTaskDraft.STATUS_REVIEW)
        self.assertIsNone(draft.reviewed_by)

    def test_other_batch_with_same_keys_is_refused(self):
        patch_data = self.edit_and_build()
        other = create_batch_from_bundle(
            bundle(), user=self.teacher, title='Другая партия', source_title='Книга')
        with self.assertRaises(TextbookPatchError):
            apply_draft_patch(other, patch_data, apply=True)

    def test_image_warning_is_recomputed_on_server(self):
        draft = self.draft()
        draft.text_latex += r' \taskpic{fig5}'
        draft.images = ['fig5']
        draft.save()
        patch_data, _ = build_draft_patch(self.baseline, batch_rows(self.batch))
        draft.text_latex = self.original['text_latex']
        draft.images = []
        draft.save()
        report = apply_draft_patch(self.batch, json.loads(json.dumps(patch_data)), apply=True)
        self.assertEqual(report['images'], [('1.2.37', ['fig5'])])
        self.assertTrue(any('изображений' in w for w in self.draft().warnings))

    def test_invalid_mask_rejects_whole_patch(self):
        patch_data = self.edit_and_build()
        patch_data['drafts'][0]['after']['answer_mask'] = '{{set: '
        with self.assertRaises(Exception):
            apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(self.draft().author_answer_latex,
                         self.original['author_answer_latex'])

    def test_patch_restores_book_order(self):
        patch_data = self.edit_and_build()
        self.assertEqual(patch_data['order'], ['1.2.37', '1.2.38'])
        # Сервер получил партию в другом порядке (старая выгрузка).
        TextbookTaskDraft.objects.filter(batch=self.batch, external_id='1.2.37').update(position=50)
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['reordered'], 1)
        self.assertEqual(list(self.batch.drafts.values_list('external_id', 'position')),
                         [('1.2.37', 10), ('1.2.38', 20)])
        patch_data['order'] = ['1.2.37']
        with self.assertRaises(TextbookPatchError):
            apply_draft_patch(self.batch, patch_data, apply=True)

    def test_tags_travel_with_patch(self):
        draft = self.draft()
        draft.tags = ['задача с параметром']
        draft.save()
        patch_data, untransferred = build_draft_patch(self.baseline, batch_rows(self.batch))
        self.assertEqual(untransferred, [])
        self.assertEqual(patch_data['drafts'][0]['after'], {'tags': ['задача с параметром']})
        draft.tags = []
        draft.save()
        apply_draft_patch(self.batch, json.loads(json.dumps(patch_data)), apply=True)
        self.assertEqual(self.draft().tags, ['задача с параметром'])

    def test_patch_built_before_tags_still_applies(self):
        patch_data = self.edit_and_build()
        # Пакет старого кода: в снимке «до» нет меток.
        for row in patch_data['drafts']:
            row['before'].pop('tags', None)
        self.draft().__class__.objects.filter(pk=self.draft().pk).update(tags=['ОГЭ'])
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['applied'], ['1.2.37'])
        self.assertEqual(report['skipped'], [])

    def test_busy_formula_worker_is_retried(self):
        from .textbook_import import TextbookImportUnavailable, normalize_answer_mask
        patch_data = self.edit_and_build()
        calls = []

        def flaky(value, *, key='answer_mask'):
            calls.append(key)
            if len(calls) == 1:
                raise TextbookImportUnavailable('занят')
            return normalize_answer_mask(value, key=key)

        with patch('problems.textbook_patches.normalize_answer_mask', flaky), \
                patch('problems.textbook_patches.time.sleep'):
            report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['applied'], ['1.2.37'])
        self.assertEqual(len(calls), 2)

    def test_unknown_field_is_refused(self):
        patch_data = self.edit_and_build()
        patch_data['drafts'][0]['after']['status'] = 'approved'
        with self.assertRaises(TextbookPatchError):
            apply_draft_patch(self.batch, patch_data, apply=True)
