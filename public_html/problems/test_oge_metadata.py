"""Метки и маски проходят весь путь от черновика до каталога."""
from types import SimpleNamespace
from django.test import SimpleTestCase, TestCase
from .oge_metadata import apply_oge_metadata, PARAMETER_TAG, GRAPH_TAG, PROOF_TAG
from .test_textbook_import import bundle
from .textbook_import import create_batch_from_bundle, commit_batch, TextbookImportError
from .textbook_topics import set_draft_topics
from .models import Task, TextbookTaskDraft, Topic, ExamItem
from .tests import make_teacher


class OgeMetadataTests(SimpleTestCase):
    def test_source_number_and_tags_are_idempotent(self):
        for number, tags in [(22, [PARAMETER_TAG, GRAPH_TAG]), (24, [PROOF_TAG]), (11, [])]:
            d = SimpleNamespace(external_id=f'{number}.1.2',
                                exam_item_codes=['OGE_2026_06'], tags=['DEMO', 'мой тег'])
            self.assertTrue(apply_oge_metadata(d, 'ostromogilsky'))
            self.assertEqual(d.exam_item_codes, [f'OGE_2026_{number:02d}'])
            self.assertEqual(d.tags, ['DEMO', 'мой тег'] + tags)
            self.assertFalse(apply_oge_metadata(d, 'ostromogilsky'))

    def test_other_books_are_not_numbered_as_oge(self):
        d = SimpleNamespace(external_id='24.1', exam_item_codes=[], tags=['DEMO'])
        self.assertFalse(apply_oge_metadata(d, 'ziv'))
        d.external_id = '26.1'
        with self.assertRaises(ValueError):
            apply_oge_metadata(d, 'ostromogilsky')


class OgeCommitTests(TestCase):
    def setUp(self):
        self.user = make_teacher()
        self.topic = Topic.objects.first()

    def prepare(self, number, answer, *, tags=None):
        payload = bundle(external_id=f'{number}.1', source_number=f'{number}.1',
                         exam_item_codes=['OGE_2026_06'], tags=tags or [],
                         author_answer_latex=answer, text_latex=f'Условие {number}')
        payload['profile'] = 'ostromogilsky'
        batch = create_batch_from_bundle(payload, user=self.user, title='ОГЭ',
                                        source_title=f'Источник {number}')
        d = batch.drafts.get()
        self.assertEqual(d.exam_item_codes, [f'OGE_2026_{number:02d}'])
        set_draft_topics(d, [self.topic.pk], self.topic.pk)
        d.status = TextbookTaskDraft.STATUS_APPROVED
        d.save()
        return batch, d

    def test_tags_and_labels_reach_catalog_even_for_old_draft(self):
        for number, expected in [(22, [PARAMETER_TAG, GRAPH_TAG]), (24, [PROOF_TAG])]:
            batch, d = self.prepare(number, '', tags=['DEMO'])
            d.tags = ['DEMO']
            d.exam_item_codes = ['OGE_2026_06']
            d.save()
            commit_batch(batch, user=self.user)
            task = Task.objects.get(source_refs__source=batch.source)
            self.assertEqual(list(task.exam_items.filter(item_number__gt=0).values_list('code', flat=True)), [f'OGE_2026_{number:02d}'])
            self.assertCountEqual(task.tags.values_list('name', flat=True), ['DEMO'] + expected)
            self.assertEqual(task.answer_mask, '')

    def test_review_shows_exam_label_and_tags_before_import(self):
        from django.urls import reverse
        batch, d = self.prepare(22, '')
        self.client.force_login(self.user)
        response = self.client.get(reverse('textbook_import_review', args=[batch.pk, d.pk]))
        self.assertContains(response, PARAMETER_TAG)
        self.assertContains(response, GRAPH_TAG)
        self.assertContains(response, ExamItem.objects.get(code='OGE_2026_22').name)

    def test_final_answer_generates_correct_mask_at_commit(self):
        for number, initial, final, expected in [
            (7, '1', '3', '{{digits: 3}}'),
            (11, '123', '234', '{{digits: 234}}'),
            (6, '1', '-0,5', '{{decimal: -0,5}}'),
            (8, '1', '1;2', ''),
        ]:
            batch, d = self.prepare(number, initial)
            d.author_answer_latex = final
            d.save()
            commit_batch(batch, user=self.user)
            task = Task.objects.get(source_refs__source=batch.source)
            self.assertEqual(task.answer_mask, expected)

    def test_missing_exam_label_rolls_back_instead_of_silent_loss(self):
        batch, d = self.prepare(11, '234')
        ExamItem.objects.filter(code='OGE_2026_11').delete()
        with self.assertRaises(TextbookImportError):
            commit_batch(batch, user=self.user)
        self.assertFalse(Task.objects.exists())
        d.refresh_from_db()
        self.assertEqual(d.status, TextbookTaskDraft.STATUS_APPROVED)

    def test_reused_task_gets_missing_mask_but_keeps_teacher_choice(self):
        batch, _ = self.prepare(11, '234')
        commit_batch(batch, user=self.user)
        task = Task.objects.get()
        task.answer_mask = ''
        task.save()
        again, _ = self.prepare(11, '234')
        commit_batch(again, user=self.user)
        task.refresh_from_db()
        self.assertEqual(task.answer_mask, '{{digits: 234}}')
        task.answer_mask = 'Ответ: {{digits: 234}}'
        task.save()
        again, _ = self.prepare(11, '234')
        commit_batch(again, user=self.user)
        task.refresh_from_db()
        self.assertEqual(task.answer_mask, 'Ответ: {{digits: 234}}')

    def test_reused_task_with_conflicting_exam_line_is_not_silently_merged(self):
        batch, _ = self.prepare(11, '234')
        commit_batch(batch, user=self.user)
        task = Task.objects.get()
        task.exam_items.add(ExamItem.objects.get(code='OGE_2026_07'))
        again, _ = self.prepare(11, '234')
        with self.assertRaises(TextbookImportError):
            commit_batch(again, user=self.user)
