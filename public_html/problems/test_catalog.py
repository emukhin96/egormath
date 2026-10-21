"""Создание, дублирование и показ материалов в каталоге и листках."""
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from worksheets.models import Worksheet, WorksheetItem
from .editor import mask_data
from .models import Task, Source, TaskSource
from .tests import make_teacher, make_student, formset_management


class CatalogTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.task = Task.objects.create(created_by=self.teacher, text_latex='Исходная',
            author_answer_latex='8', author_solution_latex='Авторское решение',
            answer_latex='9', solution_latex='AI решение', answer_mask='{{number: 8}}')
        self.sub = self.task.subitems.create(order=10, text_latex='Первый',
            author_answer_latex='2', author_solution_latex='Решение подпункта',
            answer_mask='{{number: 2}}')
        self.task.subitems.create(order=20, text_latex='Второй')
        self.source = Source.objects.create(title='Книга')
        TaskSource.objects.create(task=self.task, source=self.source, number='7')

    def test_duplicate_is_independent_and_preserves_materials(self):
        url = reverse('task_duplicate', args=[self.task.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        copy = Task.objects.exclude(pk=self.task.pk).get()
        self.assertRedirects(response, reverse('task_detail', args=[copy.pk]))
        self.assertIsNone(copy.variant_of)
        self.assertEqual(copy.author_solution_latex, self.task.author_solution_latex)
        self.assertEqual(copy.solution_latex, self.task.solution_latex)
        self.assertEqual(copy.answer_mask, self.task.answer_mask)
        self.assertEqual(copy.source_refs.get().source_id, self.source.pk)
        sub = copy.subitems.first()
        self.assertNotEqual(sub.pk, self.sub.pk)
        self.assertEqual(sub.author_solution_latex, self.sub.author_solution_latex)
        sub.text_latex = 'Изменённая копия'
        sub.save()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.text_latex, 'Первый')

    def test_worksheet_duplicate_preserves_selection_and_inserts_after(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Листок')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task, order=10,
            all_subitems=False, stars_override=2, columns_override=3)
        item.subitems.add(self.sub)
        last = WorksheetItem.objects.create(worksheet=ws, text_latex='После', order=10)
        response = self.client.post(reverse('task_duplicate', args=[self.task.pk]),
                                    {'worksheet': ws.pk, 'item': item.pk})
        self.assertRedirects(response, reverse('worksheet_detail', args=[ws.pk]))
        rows = list(ws.items.all())
        self.assertEqual([rows[0].pk, rows[2].pk], [item.pk, last.pk])
        copy = rows[1]
        self.assertEqual(copy.task.variant_of_id, self.task.pk)
        self.assertEqual((copy.stars_override, copy.columns_override), (2, 3))
        self.assertFalse(copy.all_subitems)
        self.assertEqual(list(copy.subitems.values_list('text_latex', flat=True)), ['Первый'])

    def test_database_duplicate_is_added_to_worksheet_and_keeps_context(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Исходный листок')
        original_item = WorksheetItem.objects.create(
            worksheet=ws, task=self.task, order=10)

        response = self.client.post(
            reverse('task_duplicate', args=[self.task.pk]),
            {'worksheet': ws.pk, 'item': original_item.pk, 'standalone': '1'})
        copy = Task.objects.exclude(pk=self.task.pk).get()
        copied_item = ws.items.get(task=copy)
        return_url = (reverse('task_detail', args=[copy.pk])
                      + f'?worksheet={ws.pk}&item={copied_item.pk}')

        self.assertIsNone(copy.variant_of_id)
        self.assertEqual(
            list(ws.ordered_items().values_list('task_id', flat=True)),
            [self.task.pk, copy.pk])
        self.assertRedirects(response, return_url)
        self.assertContains(self.client.get(return_url), 'Вернуться в листок')
        self.assertContains(self.client.get(return_url), 'Исходный листок')

        saved = self.client.post(
            reverse('task_manage', args=[copy.pk])
            + f'?worksheet={ws.pk}&item={copied_item.pk}&view=task',
            {'block': 'condition', 'text_latex': 'Изменённая копия',
             'scope': 'global'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['url'], return_url)
        self.assertIn('Вернуться в листок', saved.json()['html'])

    def test_duplicate_permissions(self):
        ws = Worksheet.objects.create(owner=make_teacher('other'), title='Чужой')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task)
        url = reverse('task_duplicate', args=[self.task.pk])
        self.assertEqual(self.client.post(url, {'worksheet': ws.pk, 'item': item.pk}).status_code, 403)
        self.client.force_login(make_student(self.teacher))
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(Task.objects.count(), 1)

    def test_catalog_has_toggles_without_quick_answer_or_badge(self):
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'Класс и темы')
        self.assertContains(response, 'toggle-catalog-answers')
        self.assertContains(response, 'toggle-masks')
        self.assertNotContains(response, 'textarea name="answer_latex"')
        self.assertNotContains(response, 'badge-mask')
        self.assertContains(response, 'ws-answers" hidden')

    def test_catalog_source_is_one_line_under_statement(self):
        # Источник, № и раздел — одной строкой под условием рядом с
        # «дублировать», а не столбиком в колонке «Класс и темы».
        ref = self.task.source_refs.get()
        ref.source_path = ['Глава 1. Дроби', '§ 2. Сокращение']
        ref.save(update_fields=['source_path'])
        response = self.client.get(reverse('task_list'))
        html = response.content.decode()
        meta = html.split('class="task-meta catalog-row-meta"', 1)[1].split('</td>', 1)[0]
        self.assertIn('Книга · № 7 › Глава 1. Дроби › § 2. Сокращение', meta)
        self.assertIn('дублировать', meta)
        self.assertNotIn('import-section-path', html)

    def test_catalog_source_uses_short_title_and_path_tail(self):
        # Полное «Авторы. Название» и вся глава — в подсказке; в строке
        # короткое имя книги и два последних раздела пути.
        self.source.author = 'М. И. Шабунин'
        self.source.short_title = 'Шабунин, пособие 10'
        self.source.save()
        ref = self.task.source_refs.get()
        ref.source_path = ['Глава X. Функции', 'Дидактические материалы', 'ДКР X.1', 'Вариант 5']
        ref.save(update_fields=['source_path'])
        html = self.client.get(reverse('task_list')).content.decode()
        meta = html.split('class="task-meta catalog-row-meta"', 1)[1].split('</td>', 1)[0]
        self.assertIn('>Шабунин, пособие 10 · № 7 › … › ДКР X.1 › Вариант 5</span>', meta)
        self.assertIn('title="М. И. Шабунин. Книга · № 7 › Глава X. Функции › '
                      'Дидактические материалы › ДКР X.1 › Вариант 5"', meta)
        self.assertIn('>Шабунин, пособие 10<span class="sidebar-count">', html)

    def test_builder_answers_are_hidden_before_scripts_run(self):
        worksheet = Worksheet.objects.create(owner=self.teacher, title='Листок')
        WorksheetItem.objects.create(worksheet=worksheet, task=self.task)
        response = self.client.get(reverse('worksheet_detail', args=[worksheet.pk]))
        self.assertContains(response, 'ws-answers" hidden')

    def test_creation_saves_author_fields_and_subitem_mask(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'problem-columns')
        data = {'text_latex': 'Новая уникальная', 'stars': '0', 'columns': '1',
                'author_answer_latex': '4', 'author_solution_latex': 'Сложение',
                **formset_management('source_refs'), **formset_management('images'),
                **formset_management('subitems', total=1),
                'subitems-0-order': '1', 'subitems-0-text_latex': 'Один',
                'subitems-0-author_answer_latex': '2',
                'subitems-0-author_solution_latex': 'Автор подпункта',
                'subitems-0-answer_mask': '{{number: 2}}'}
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(text_latex='Новая уникальная')
        self.assertEqual(task.author_answer_latex, '4')
        self.assertEqual(task.subitems.get().answer_mask, '{{number: 2}}')

    def test_inline_preview_prefills_reference_without_check(self):
        self.task.subitems.all().delete()
        self.task.answer_mask = r'$S=${{number: \sqrt{2}}} {{choice: *да|нет}} {{order: a|b|c}}'
        preview = mask_data(self.task, include_preview=True)[0]['preview_html']
        self.assertIn(r'\sqrt{2}</math-field>', preview)
        self.assertIn('value="да" selected', preview)
        self.assertEqual(preview.count(' selected'), 4)
        self.assertNotIn('check-badge', preview)

    def test_mask_data_uses_task_subitem_letters(self):
        self.assertEqual(
            [answer['label'] for answer in mask_data(self.task)],
            ['а', 'б'])


class CatalogPerformanceTests(TestCase):
    def test_prefetched_taxonomy_matches_unprepared_without_queries(self):
        from .models import Topic, GradeBand, TaskTopic, FacetValue, ExamItem
        from .rubricator import (seed_rubricator, task_taxonomy_state,
                                 worksheet_taxonomy_state)
        from .views import filter_tasks
        from django.http import QueryDict
        seed_rubricator()
        teacher = make_teacher()
        task = Task.objects.create(text_latex='Уравнение', created_by=teacher)
        topic = Topic.objects.filter(code__isnull=False).first()
        TaskTopic.objects.create(task=task, topic=topic, role=TaskTopic.ROLE_PRIMARY)
        task.grade_bands.add(GradeBand.objects.first())
        task.facet_values.add(FacetValue.objects.first())
        task.exam_items.add(ExamItem.objects.first())
        expected = task_taxonomy_state(task)
        self.assertEqual(expected['primary'], topic.pk)
        prepared = filter_tasks(QueryDict(), teacher).get(pk=task.pk)
        with self.assertNumQueries(0):
            self.assertEqual(task_taxonomy_state(prepared), expected)
        worksheet = Worksheet.objects.create(owner=teacher, title='Листок')
        worksheet.topics.add(topic)
        worksheet.grade_bands.add(GradeBand.objects.first())
        expected = worksheet_taxonomy_state(worksheet)
        prepared = Worksheet.objects.prefetch_related('topics', 'grade_bands').get(pk=worksheet.pk)
        with self.assertNumQueries(0):
            self.assertEqual(worksheet_taxonomy_state(prepared), expected)

    def test_equal_creation_dates_have_stable_pages(self):
        from django.core.paginator import Paginator
        from django.http import QueryDict
        from django.utils import timezone
        from .views import filter_tasks
        tasks = Task.objects.bulk_create([Task(text_latex=str(i)) for i in range(51)])
        Task.objects.update(created_at=timezone.now())
        paginator = Paginator(filter_tasks(QueryDict(), make_teacher()), 25)
        ids = [task.pk for n in paginator.page_range for task in paginator.page(n)]
        self.assertEqual(ids, sorted((task.pk for task in tasks), reverse=True))
        self.assertEqual(len(set(ids)), 51)


class TaxonomyCatalogCacheTests(TransactionTestCase):
    def setUp(self):
        from django.core.cache import caches
        from .rubricator import TAXONOMY_CACHE_ALIAS, seed_rubricator

        caches[TAXONOMY_CACHE_ALIAS].clear()
        seed_rubricator()

    def test_warm_catalog_reads_only_fresh_counts(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .rubricator import taxonomy_catalog

        with CaptureQueriesContext(connection) as cold_queries:
            cold = taxonomy_catalog()
        with self.assertNumQueries(1):
            warm = taxonomy_catalog()

        self.assertGreater(len(cold_queries), 1)
        self.assertEqual(warm, cold)

    def test_reference_change_invalidates_catalog(self):
        from .models import Topic
        from .rubricator import taxonomy_catalog

        catalog = taxonomy_catalog()
        topic = Topic.objects.get(code='ALG.07.03')
        old_name = topic.name
        topic.name = 'Касательная: обновлённая тема'
        topic.save(update_fields=['name'])

        refreshed = taxonomy_catalog()

        before = next(row for row in catalog['topics']
                      if row['id'] == topic.pk)
        after = next(row for row in refreshed['topics']
                     if row['id'] == topic.pk)
        self.assertEqual(before['name'], old_name)
        self.assertEqual(after['name'], topic.name)

    def test_task_counts_are_not_stale_in_cached_catalog(self):
        from .models import TaskTopic, Topic
        from .rubricator import taxonomy_catalog

        topic = Topic.objects.get(code='ALG.07.03')
        before = next(row['count'] for row in taxonomy_catalog()['topics']
                      if row['id'] == topic.pk)
        # Счётчики каталога — по общим задачам (кэш один на всех пользователей).
        task = Task.objects.create(text_latex='Новая задача для счётчика', is_shared=True)
        TaskTopic.objects.create(task=task, topic=topic)

        after = next(row['count'] for row in taxonomy_catalog()['topics']
                     if row['id'] == topic.pk)
        self.assertEqual(after, before + 1)


class TaxonomyCatalogEndpointTests(TestCase):
    """Каталог рубрикатора — отдельным кэшируемым ответом, не в каждой странице."""

    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)

    def test_page_carries_link_not_catalog(self):
        html = self.client.get(reverse('task_list')).content.decode()
        url = reverse('taxonomy_catalog_json')
        self.assertIn('id="taxonomy-catalog"', html)
        self.assertIn(f'data-src="{url}"', html)
        self.assertNotIn('"topics":', html)

    def test_json_etag_and_cache(self):
        url = reverse('taxonomy_catalog_json')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        data = response.json()
        self.assertIn('topics', data)
        self.assertTrue(data['topics'])
        self.assertIn('max-age=', response['Cache-Control'])
        again = self.client.get(url, HTTP_IF_NONE_MATCH=response['ETag'])
        self.assertEqual(again.status_code, 304)
        # Caddy дописывает суффикс сжатия внутри кавычек
        zstd = response['ETag'][:-1] + '-zstd"'
        self.assertEqual(self.client.get(url, HTTP_IF_NONE_MATCH=zstd).status_code, 304)

    def test_counts_are_fresh_after_new_task(self):
        url = reverse('taxonomy_catalog_json')
        before = self.client.get(url)
        topic = next(t for t in before.json()['topics'] if t['leaf'])
        task = Task.new_for(self.teacher, text_latex='Новая')
        task.topics.add(topic['id'])
        after = self.client.get(url, HTTP_IF_NONE_MATCH=before['ETag'])
        self.assertEqual(after.status_code, 200)
        count = next(t['count'] for t in after.json()['topics'] if t['id'] == topic['id'])
        self.assertEqual(count, topic['count'] + 1)

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse('taxonomy_catalog_json'))
        self.assertEqual(response.status_code, 302)
