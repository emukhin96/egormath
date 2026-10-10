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
                               build_draft_patch, current_rows)

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

    def test_review_button_fills_pending_masks(self):
        draft = self.batch.drafts.get(external_id='I.2')
        draft.answer_mask = ''
        draft.warnings = [DEFERRED_MASK_WARNING]
        draft.save()
        review = reverse('textbook_import_review', args=[self.batch.pk, draft.pk])
        self.assertContains(self.client.get(review), 'Подобрать маски сейчас')
        response = self.client.post(
            reverse('textbook_import_review_masks', args=[self.batch.pk, draft.pk]))
        self.assertRedirects(response, review)
        draft.refresh_from_db()
        self.assertEqual(draft.answer_mask, '{{number: 4}}')
        self.assertNotIn(DEFERRED_MASK_WARNING, draft.warnings)
        self.assertContains(self.client.get(review), 'Как увидит ученик')

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
        self.baseline = current_rows(self.batch)

    def edit_and_build(self):
        draft = self.batch.drafts.get(external_id='1.2.37')
        draft.author_answer_latex = r'$x=\pm 2$'
        draft.answer_mask = '{{set: -2; 2}}'
        draft.topic = self.topic_b
        draft.topic_ids = [self.topic_b.pk]
        draft.save()
        patch_data = build_draft_patch(self.baseline, current_rows(self.batch))
        # Возвращаем партию к исходному состоянию — как сервер до переноса.
        draft.author_answer_latex = self.baseline[0]['author_answer_latex']
        draft.answer_mask = self.baseline[0]['answer_mask']
        draft.topic = self.topic_a
        draft.topic_ids = [self.topic_a.pk]
        draft.save()
        return json.loads(json.dumps(patch_data))

    def test_patch_has_only_changed_fields(self):
        patch_data = self.edit_and_build()
        self.assertEqual([row['external_id'] for row in patch_data['drafts']],
                         ['1.2.37'])
        self.assertEqual(set(patch_data['drafts'][0]['fields']),
                         {'author_answer_latex', 'answer_mask',
                          'topic_code', 'topic_codes'})

    def test_dry_run_changes_nothing_and_apply_writes(self):
        patch_data = self.edit_and_build()
        report = apply_draft_patch(self.batch, patch_data)
        self.assertEqual(report['applied'], ['1.2.37'])
        draft = self.batch.drafts.get(external_id='1.2.37')
        self.assertEqual(draft.answer_mask, self.baseline[0]['answer_mask'])
        apply_draft_patch(self.batch, patch_data, apply=True)
        draft.refresh_from_db()
        self.assertEqual(draft.author_answer_latex, r'$x=\pm 2$')
        self.assertEqual(draft.answer_mask, '{{set: -2; 2}}')
        self.assertEqual(draft.topic_id, self.topic_b.pk)
        self.assertEqual(draft.topic_ids, [self.topic_b.pk])

    def test_later_teacher_edit_is_not_overwritten(self):
        patch_data = self.edit_and_build()
        draft = self.batch.drafts.get(external_id='1.2.37')
        draft.author_answer_latex = 'Правка учителя'
        draft.save()
        report = apply_draft_patch(self.batch, patch_data, apply=True)
        self.assertEqual(report['applied'], [])
        self.assertIn('author_answer_latex', report['skipped'][0][1])
        draft.refresh_from_db()
        self.assertEqual(draft.author_answer_latex, 'Правка учителя')

    def test_invalid_mask_rejects_whole_patch(self):
        patch_data = self.edit_and_build()
        patch_data['drafts'][0]['fields']['answer_mask']['after'] = '{{set: '
        with self.assertRaises(Exception):
            apply_draft_patch(self.batch, patch_data, apply=True)
        draft = self.batch.drafts.get(external_id='1.2.37')
        self.assertEqual(draft.author_answer_latex, self.baseline[0]['author_answer_latex'])

    def test_unknown_field_is_refused(self):
        patch_data = self.edit_and_build()
        patch_data['drafts'][0]['fields']['status'] = {'before': 'needs_review',
                                                       'after': 'approved'}
        with self.assertRaises(TextbookPatchError):
            apply_draft_patch(self.batch, patch_data, apply=True)
