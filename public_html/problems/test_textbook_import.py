import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from problems.models import (Task, TaskSource, TextbookImportBatch,
                             TextbookTaskDraft, Topic)
from problems.tests import make_teacher
from problems.textbook_import import (TextbookImportError, commit_batch,
                                      create_batch_from_bundle)
from worksheets.models import Collection, WorksheetItem


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

    def test_upload_creates_only_drafts(self):
        self.client.login(username='teacher1', password='pass12345')
        upload = SimpleUploadedFile(
            'import.json', json.dumps(bundle()).encode(),
            content_type='application/json')
        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Партия', 'source_title': 'Задачник',
            'source_author': 'Автор', 'bundle': upload,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TextbookImportBatch.objects.count(), 1)
        self.assertEqual(TextbookTaskDraft.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 0)

    def test_commit_requires_review(self):
        batch = self.create_batch()
        with self.assertRaisesMessage(TextbookImportError, 'непроверенных'):
            commit_batch(batch, user=self.teacher)
        self.assertEqual(Task.objects.count(), 0)

    def test_commit_requires_rubricator_topic(self):
        batch = self.create_batch()
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED)
        with self.assertRaisesMessage(TextbookImportError, 'тема рубрикатора'):
            commit_batch(batch, user=self.teacher)
        self.assertEqual(Task.objects.count(), 0)

    def test_commit_separates_author_data_and_builds_collection(self):
        topic = Topic.objects.create(name='Квадратные уравнения')
        batch = self.create_batch()
        draft = batch.drafts.get()
        draft.status = TextbookTaskDraft.STATUS_APPROVED
        draft.topic = topic
        draft.save()

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
        self.assertTrue(WorksheetItem.objects.filter(
            worksheet=leaf.worksheet, task=task).exists())
        self.assertEqual(list(task.topics.all()), [topic])

        self.assertEqual(commit_batch(batch, user=self.teacher), {
            'created': 0, 'reused': 0, 'collections': 0})
        self.assertEqual(Task.objects.count(), 1)

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

    def test_review_pages_render(self):
        batch = self.create_batch()
        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(
            reverse('textbook_import_detail', args=[batch.pk]))
        self.assertContains(detail, '1.2.37')
        review = self.client.get(reverse(
            'textbook_import_review', args=[batch.pk, batch.drafts.get().pk]))
        self.assertContains(review, 'Авторский ответ')
        self.assertContains(review, 'Сохранить и дальше')
