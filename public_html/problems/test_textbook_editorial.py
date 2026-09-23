"""Регрессии сохранения происхождения материалов при сверке и публикации."""
import json
from django.test import TestCase
from django.urls import reverse
from problems.tests import make_teacher
from problems.models import TextbookTaskDraft, Topic
from problems.test_textbook_import import bundle
from problems.textbook_import import create_batch_from_bundle, commit_batch
from problems.textbook_parser import finalize_draft_images


class EditorialImportTests(TestCase):
    def setUp(self):
        self.user = make_teacher()
        self.client.force_login(self.user)

    def batch(self, **fields):
        return create_batch_from_bundle(bundle(**fields), user=self.user,
                                       title='Редакторские поля', source_title='Книга')

    def publish(self, batch):
        draft = batch.drafts.get()
        draft.topic = Topic.objects.create(name='Тема')
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save()
        commit_batch(batch, user=self.user)
        draft.refresh_from_db()
        return draft.imported_task

    def test_both_sources_survive_review_and_publication(self):
        batch = self.batch(answer_latex='$2$', solution_latex='Подробный разбор.')
        draft = batch.drafts.get()
        response = self.client.post(reverse('textbook_import_review', args=[batch.pk, draft.pk]), {
            'external_id': draft.external_id, 'source_number': draft.source_number,
            'text_latex': draft.text_latex, 'subitems': '[]', 'status': 'needs_review',
            'author_answer_latex': draft.author_answer_latex,
            'author_solution_latex': draft.author_solution_latex,
            'answer_latex': '$3$', 'solution_latex': 'Новый разбор.',
            'answer_mask': '{{number: 3}}',
        })
        self.assertEqual(response.status_code, 302)
        task = self.publish(batch)
        self.assertIn('pm2', task.author_answer_latex)
        self.assertEqual(task.author_solution_latex, 'Извлечём квадратный корень.')
        self.assertEqual(task.answer_latex, '$3$')
        self.assertEqual(task.solution_latex, 'Новый разбор.')
        self.assertEqual(task.answer_mask, '{{number: 3}}')

    def test_subitem_reordering_preserves_sources_and_mask(self):
        batch = self.batch(author_answer_latex='', author_solution_latex='', subitems=[
            {'label': '1', 'text_latex': 'Первый', 'author_answer_latex': '$1$',
             'answer_latex': '$2$', 'solution_latex': 'Первое решение.', 'answer_mask': '{{number: 2}}'},
            {'label': '2', 'text_latex': 'Второй', 'solution_latex': 'Второе решение.'},
        ])
        draft = batch.drafts.get()
        self.client.post(reverse('textbook_import_review', args=[batch.pk, draft.pk]), {
            'external_id': draft.external_id, 'source_number': draft.source_number,
            'text_latex': draft.text_latex, 'subitems': json.dumps(list(reversed(draft.subitems))),
            'status': 'needs_review', 'subitem_solution_0': 'Исправленное первое решение.',
        })
        draft.refresh_from_db()
        self.assertEqual(draft.subitems[1]['solution_latex'], 'Исправленное первое решение.')
        self.assertEqual(draft.subitems[1]['author_answer_latex'], '$1$')
        self.assertEqual(draft.subitems[1]['answer_mask'], '{{number: 2}}')
        task = self.publish(batch)
        subs = list(task.subitems.order_by('order'))
        self.assertEqual(subs[1].answer_latex, '$2$')
        self.assertEqual(subs[1].solution_latex, 'Исправленное первое решение.')

    def test_editorial_images_are_finalized_without_changing_authorship(self):
        draft = TextbookTaskDraft(text_latex='Условие', answer_latex=r'\taskpic{answer.png}',
            subitems=[{'label': '1', 'text_latex': 'Пункт', 'solution_latex': r'\taskpic{solution.png}'}])
        finalize_draft_images(draft)
        self.assertEqual(draft.images, ['answer.png', 'solution.png'])
        self.assertEqual(draft.answer_latex, r'\taskpic{1}')
        self.assertEqual(draft.subitems[0]['solution_latex'], r'\taskpic{2}')
        self.assertEqual(draft.author_answer_latex, '')

    def test_common_material_is_preserved_with_subitems(self):
        batch = self.batch(author_answer_latex='Пять вариантов.',
            author_solution_latex='Общее указание из книги.',
            solution_latex='Общий редакторский разбор.',
            subitems=[{'label': '1', 'text_latex': 'Пункт',
                       'author_answer_latex': '$1$', 'solution_latex': 'Разбор пункта.'}])
        task = self.publish(batch)
        self.assertEqual(task.author_answer_latex, 'Пять вариантов.')
        self.assertEqual(task.author_solution_latex, 'Общее указание из книги.')
        self.assertEqual(task.solution_latex, 'Общий редакторский разбор.')

    def test_missing_answers_filter_includes_editorial_material(self):
        from problems.views import _filter_drafts_without_answers
        common = self.batch(author_answer_latex='', answer_latex='$2$').drafts.get()
        parts = self.batch(author_answer_latex='', subitems=[
            {'label': '1', 'text_latex': 'Пункт', 'answer_latex': '$3$'},
        ]).drafts.get()
        empty = self.batch(author_answer_latex='').drafts.get()
        result = _filter_drafts_without_answers(TextbookTaskDraft.objects.filter(
            pk__in=[common.pk, parts.pk, empty.pk]))
        self.assertEqual(list(result.values_list('pk', flat=True)), [empty.pk])
