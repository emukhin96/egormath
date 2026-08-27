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
        parent = Collection.objects.get(source_path=['Алгебра'])
        self.assertFalse(parent.is_published)
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

    def test_reimport_rejects_changed_subitem_text(self):
        topic = Topic.objects.create(name='Тема подпунктов')
        first_payload = bundle(subitems=[{
            'label': 'а', 'text_latex': '$1+1$',
            'author_answer_latex': '2',
        }])
        first = self.create_batch(first_payload)
        first.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        commit_batch(first, user=self.teacher)

        second_payload = bundle(subitems=[{
            'label': 'а', 'text_latex': '$2+2$',
            'author_answer_latex': '4',
        }])
        second = self.create_batch(second_payload)
        second.drafts.update(
            status=TextbookTaskDraft.STATUS_APPROVED, topic=topic)
        with self.assertRaisesMessage(TextbookImportError, 'условие подпункта'):
            commit_batch(second, user=self.teacher)

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
        self.assertContains(review, 'Сохранить и дальше')

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

    def test_review_clears_previous_solution_match(self):
        payload = bundle(author_solution_latex='')
        payload['tasks'].append(dict(
            payload['tasks'][0], external_id='solution-37',
            source_number='решение 37',
            author_solution_latex='Полное решение.'))
        batch = self.create_batch(payload)
        draft = batch.drafts.get(external_id='1.2.37')
        self.client.login(username='teacher1', password='pass12345')
        url = reverse(
            'textbook_import_review', args=[batch.pk, draft.pk])
        base_form = {
            'external_id': draft.external_id,
            'source_number': draft.source_number,
            'text_latex': draft.text_latex,
            'subitems': '[]',
            'author_answer_latex': draft.author_answer_latex,
            'author_solution_latex': '',
            'status': TextbookTaskDraft.STATUS_REVIEW,
        }

        response = self.client.post(
            url, {**base_form, 'copy_solution_from': 'solution-37'})
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.solution_source_external_id, 'solution-37')

        response = self.client.post(
            url, {**base_form, 'copy_solution_from': '',
                  'author_solution_latex': 'Решение исправлено вручную.'})
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.solution_source_external_id, '')
        self.assertEqual(
            draft.author_solution_latex, 'Решение исправлено вручную.')
