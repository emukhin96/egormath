import io
import json
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from problems.models import (Task, TaskImage, TaskSource,
                             TextbookImportBatch, TextbookTaskDraft, Topic)
from problems.tests import make_teacher
from problems.textbook_import import (TextbookImportError, attach_image_archive,
                                      commit_batch, create_batch_from_bundle,
                                      repair_ziv_batch_leaks)
from problems.textbook_topics import (match_topic_candidates,
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
        self.assertEqual(draft.author_answer_latex, '2.')
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
        self.assertEqual(draft.author_answer_latex, '')
        self.assertEqual(draft.author_solution_latex, '')
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
            commit_batch(batch, user=self.teacher)
        self.assertEqual(Task.objects.count(), 0)

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
        self.assertContains(detail, '>Импорт<')

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
        self.assertNotContains(response, 'name="author_answer_latex"')
        self.assertNotContains(response, 'name="author_solution_latex"')
        self.assertContains(response, 'data-tax-picker')
        self.assertContains(response, 'data-single="1"')
        self.assertContains(response, 'Тема: код или название')
        self.assertIn(str(first_topic.pk), response.context['selected_json'])

        response = self.client.post(url, {
            'external_id': draft.external_id,
            'source_number': draft.source_number,
            'text_latex': draft.text_latex,
            'subitems': json.dumps(draft.subitems),
            'subitem_author_answer_0': 'Новый ответ.',
            'subitem_author_solution_0': 'Новое решение.',
            'author_answer_latex': 'Не должно сохраниться.',
            'author_solution_latex': 'Не должно сохраниться.',
            'topic': str(second_topic.pk),
            'status': TextbookTaskDraft.STATUS_REVIEW,
        })

        self.assertRedirects(response, reverse(
            'textbook_import_review', args=[batch.pk, draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.topic, second_topic)
        self.assertEqual(
            draft.subitems[0]['author_answer_latex'], 'Новый ответ.')
        self.assertEqual(
            draft.subitems[0]['author_solution_latex'], 'Новое решение.')
        self.assertEqual(draft.author_answer_latex, '')
        self.assertEqual(draft.author_solution_latex, '')

    def test_commit_never_writes_parent_author_fields_for_subitems(self):
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
        self.assertEqual(task.author_answer_latex, '')
        self.assertEqual(task.author_solution_latex, '')
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
                'subitems': json.dumps(list(reversed(original))),
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
        self.assertContains(response, 'Состав будущей подборки')
        self.assertContains(response, 'data-single="1"')

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
        self.assertContains(response, '>Ответ<')
        self.assertContains(response, '>Решение<')
        self.assertContains(response, 'import-status-review')
        self.assertContains(response, 'title="Не проверена"')
        self.assertContains(response, '$1+1$', html=False)
        self.assertContains(response, 'есть: 1/2')
        html = response.content.decode()
        self.assertGreaterEqual(html.count('Вычислите:'), 2)
        self.assertGreaterEqual(html.count('$1+1$'), 2)
        self.assertNotIn('class="ws-num"', html)
        self.assertNotIn('а) а)', html)

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

        group = response.context['selected_group']
        page = response.context['collection_page']
        self.assertEqual(group['count'], 51)
        self.assertEqual(len(page.object_list), 50)
        self.assertEqual(page.paginator.num_pages, 2)

        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]), {
                'section': group['token'], 'collection_page': 2,
        })
        self.assertEqual(
            len(response.context['collection_page'].object_list), 1)

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
        token = response.context['selected_section']
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
        self.assertEqual(draft.author_answer_latex, '$1<2$.')

    def test_status_filter_keeps_selected_section(self):
        batch = self.create_batch()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse(
            'textbook_import_detail', args=[batch.pk]))
        token = response.context['selected_section']
        self.assertContains(response, f'status=needs_review')
        self.assertContains(response, f'section={token}')
        self.assertNotContains(response, '<optgroup')
        self.assertContains(response, 'import-bulk-form')
        self.assertContains(response, 'name="ids"')

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
        self.assertEqual(second.topic, topic)

        response = self.client.post(url, {
            'ids': [str(second.pk)],
            'delete': '1',
            'next': reverse('textbook_import_detail', args=[batch.pk]),
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(batch.drafts.filter(pk=second.pk).exists())
        self.assertTrue(batch.drafts.filter(pk=first.pk).exists())

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
