"""Импорт сохраняет самостоятельные вопросы, но не выпускает неполный блок."""
from django.test import TestCase
from problems.models import Source, Task, TextbookImportBatch, TextbookTaskDraft, Topic
from problems.tests import make_teacher
from problems.task_blocks import bind_oge_draft_blocks
from problems.textbook_import import commit_batch, TextbookImportError


class BlockImportTests(TestCase):
    def setUp(self):
        self.user = make_teacher()
        self.batch = TextbookImportBatch.objects.create(
            title='ОГЭ', profile='ostromogilsky', created_by=self.user,
            source=Source.objects.create(title='Источник'))
        self.topic = Topic.objects.create(name='Практические задачи', code='TEST.BLOCK')
        self.drafts = [TextbookTaskDraft.objects.create(
            batch=self.batch, external_id=f'{n}.4.2', source_number=f'{n}.4.2',
            source_path=['Участки'], collection_title='Участки', collection_key='plots',
            text_latex=f'Общее условие. Вопрос {n}', author_answer_latex=str(n),
            topic=self.topic, status='approved') for n in range(1, 6)]

    def test_binding_is_idempotent_and_keeps_statuses(self):
        self.assertEqual(bind_oge_draft_blocks(self.batch), 5)
        self.assertEqual(bind_oge_draft_blocks(self.batch), 0)
        self.assertEqual(self.batch.drafts.values('block').distinct().count(), 1)
        self.assertEqual(self.batch.drafts.filter(status='approved').count(), 5)

    def test_common_block_preview_shows_condition_once_and_all_questions(self):
        common = (r'\taskpic{1}' + '\n\n'
                  + 'Общее описание участка и расположения построек. ' * 4)
        words = ['Первый', 'Второй', 'Третий', 'Четвёртый', 'Пятый']
        for draft, word in zip(self.drafts, words):
            draft.text_latex = common.rstrip() + '\n\n' + word + ' вопрос.'
            draft.images = ['plan']
            draft.save(update_fields=['text_latex', 'images'])
        bind_oge_draft_blocks(self.batch)
        block = self.batch.drafts.first().block_id
        self.client.force_login(self.user)
        response = self.client.get(f'/problems/imports/{self.batch.pk}/blocks/{block}/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['combined'])
        self.assertContains(response, '<h1>' + response.context['task_block'].title + '</h1>', html=True)
        self.assertContains(response, 'Общее описание участка', count=4)
        self.assertContains(response, 'Рисунок plan не сопоставлен.', count=1)
        for word in words:
            self.assertContains(response, word + ' вопрос.')
        self.assertEqual(self.batch.drafts.filter(status='approved').count(), 5)

    def test_block_preview_denies_another_teacher(self):
        bind_oge_draft_blocks(self.batch)
        self.client.force_login(make_teacher('another'))
        block = self.batch.drafts.first().block_id
        response = self.client.get(f'/problems/imports/{self.batch.pk}/blocks/{block}/')
        self.assertEqual(response.status_code, 403)

    def test_selection_imports_whole_approved_block(self):
        result = commit_batch(self.batch, user=self.user,
                              draft_ids=[self.drafts[2].pk], require_complete=False)
        self.assertEqual(result['created'], 5)
        tasks = list(Task.objects.filter(block__source=self.batch.source).order_by('block_position'))
        self.assertEqual([t.block_position for t in tasks], [1, 2, 3, 4, 5])
        self.assertEqual([t.author_answer_latex for t in tasks], ['1', '2', '3', '4', '5'])
        worksheet = self.batch.source.collections.first().worksheet
        self.assertEqual(list(worksheet.ordered_items().filter(task__isnull=False)
                              .values_list('task__block_position', flat=True)), [1, 2, 3, 4, 5])

    def test_unreviewed_sibling_blocks_partial_import(self):
        self.drafts[3].status = 'needs_review'
        self.drafts[3].save(update_fields=['status'])
        with self.assertRaises(TextbookImportError):
            commit_batch(self.batch, user=self.user,
                         draft_ids=[self.drafts[0].pk], require_complete=False)
        self.assertFalse(Task.objects.filter(block__source=self.batch.source).exists())
        self.assertEqual(self.batch.drafts.filter(status='imported').count(), 0)
