"""Очистка черновиков и будущая генерация масок не теряют ручные правки."""
import tempfile
from pathlib import Path
from django.core.management import call_command
from django.test import TestCase
from problems.models import Task, Topic, TextbookTaskDraft
from problems.tests import make_teacher
from problems.textbook_import import create_batch_from_bundle, commit_batch
from problems.textbook_topics import set_draft_topics


class EgeCleanupCommandTests(TestCase):
    def test_cleanup_then_commit_mask_and_preserve_manual_mask(self):
        from problems.rubricator import seed_rubricator
        seed_rubricator()
        teacher = make_teacher()
        batch = create_batch_from_bundle({'schema_version': 1, 'profile': 'ostromogilsky_ege',
            'tasks': [{'external_id': '9.1.2', 'source_number': '9.1.2',
                       'text_latex': 'Ручное уточнение. Найдите количество точек: 3.\nОтветы',
                       'author_answer_latex': '3', 'exam_item_codes': ['EGE_PROFILE_2027_09']}]},
            user=teacher, title='ЕГЭ', source_title='Тест')
        with tempfile.TemporaryDirectory() as directory:
            for index in range(2):
                call_command('clean_ege_drafts', batch=batch.pk,
                             report=Path(directory)/f'{index}.json', commit=True)
        draft = batch.drafts.get()
        self.assertEqual(draft.text_latex, 'Ручное уточнение. Найдите количество точек: $3$.')
        self.assertEqual(Task.objects.count(), 0)
        topic = Topic.objects.get(code='ARI.03')
        set_draft_topics(draft, [topic.pk], topic.pk)
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save()
        commit_batch(batch, user=teacher)
        task = Task.objects.get()
        self.assertEqual(task.answer_mask, '{{digits: 3}}')
        task.answer_mask = '{{number: 3}}'
        task.save()
        commit_batch(batch, user=teacher)
        task.refresh_from_db()
        self.assertEqual(task.answer_mask, '{{number: 3}}')

    def test_commit_generates_subitem_masks(self):
        from problems.rubricator import seed_rubricator
        seed_rubricator()
        teacher = make_teacher()
        batch = create_batch_from_bundle({'schema_version': 1, 'profile': 'ostromogilsky_ege',
            'tasks': [{'external_id': '14.1', 'source_number': '14.1', 'text_latex': 'Уравнение.',
                       'exam_item_codes': ['EGE_PROFILE_2027_14'], 'subitems': [
                           {'label': 'а', 'text_latex': 'Решите.', 'author_answer_latex': r'\pi n'},
                           {'label': 'б', 'text_latex': 'Корни на отрезке.', 'author_answer_latex': r'0, \pi'}]}]},
            user=teacher, title='ЕГЭ', source_title='Тест')
        draft = batch.drafts.get()
        topic = Topic.objects.get(code='ARI.03')
        set_draft_topics(draft, [topic.pk], topic.pk)
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.save()
        commit_batch(batch, user=teacher)
        masks = list(Task.objects.get().subitems.order_by('order').values_list('answer_mask', flat=True))
        self.assertIn('series:', masks[0])
        self.assertIn('range:', masks[1])
