"""Авторские листки в подборках: перенос туда и обратно, видимость."""
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from problems.models import ExamItem, ExamModel, Task
from problems.tests import make_teacher
from worksheets.models import Collection, Worksheet, WorksheetItem
from worksheets.tests import make_worksheet

from .authored import (AuthoredError, move_to_collections,
                       move_to_worksheets, section_for)
from .corpus import SOURCE_TITLE


class AuthoredSectionTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)

    def test_section_by_grade_exam_and_misc(self):
        self.assertEqual(section_for(self.worksheet)[1], 'Разное')
        self.worksheet.grade = 8
        self.assertEqual(section_for(self.worksheet)[:2], ('grade:8', '8 класс'))
        self.worksheet.grade = 11
        self.assertEqual(section_for(self.worksheet)[:2], ('grade:10', '10–11 класс'))
        model, _ = ExamModel.objects.get_or_create(
            exam_type=ExamModel.TYPE_OGE, exam_year=2026,
            defaults={'code': 'OGE_2026', 'name': 'ОГЭ 2026'})
        item, _ = ExamItem.objects.get_or_create(
            exam_model=model, item_number=1,
            defaults={'code': 'OGE_2026_01', 'name': '№1'})
        tasks = [row.task for row in self.worksheet.ordered_items()]
        tasks[0].exam_items.add(item)
        # Одна задача из двух — не большинство.
        self.assertEqual(section_for(self.worksheet)[1], '10–11 класс')
        tasks[1].exam_items.add(item)
        self.assertEqual(section_for(self.worksheet)[:2], ('exam:OGE', 'ОГЭ'))


class AuthoredMoveTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.other = make_teacher('teacher2')
        self.worksheet = make_worksheet(self.teacher, title='Проценты')
        self.worksheet.grade = 6
        self.worksheet.comment = 'corpus:6 класс/percent'
        self.worksheet.save()
        self.client.login(username='teacher1', password='pass12345')

    def test_move_creates_private_collection_in_grade_section(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        self.assertEqual(collection.source.title, SOURCE_TITLE)
        self.assertEqual(collection.parent.worksheet.title, '6 класс')
        self.assertEqual(collection.locator, 'corpus:6 класс/percent')
        self.assertFalse(collection.is_published)
        self.assertTrue(collection.parent.is_published)
        # Раздел переиспользуется, повторный перенос — ошибка.
        second = make_worksheet(self.teacher, title='Дроби')
        second.grade = 6
        second.save()
        self.assertEqual(
            move_to_collections(second, self.other).parent, collection.parent)
        with self.assertRaises(AuthoredError):
            move_to_collections(self.worksheet, self.teacher)
        with self.assertRaises(AuthoredError):
            move_to_collections(
                Worksheet.objects.create(title='Пустой', owner=self.teacher),
                self.teacher)

    def test_section_container_is_protected_from_teachers(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        second = make_worksheet(self.other, title='Чужая')
        second.grade = 6
        second.save()
        foreign = move_to_collections(second, self.other)
        section = collection.parent
        self.assertEqual(foreign.parent, section)
        self.assertEqual(section.worksheet.owner.username, 'authored-sections')
        self.assertFalse(section.worksheet.owner.is_active)
        # Ни первый, ни второй учитель не могут удалить или править контейнер.
        for username in ('teacher1', 'teacher2'):
            self.client.login(username=username, password='pass12345')
            response = self.client.post(
                reverse('worksheet_delete', args=[section.worksheet_id]))
            self.assertEqual(response.status_code, 404)
            response = self.client.get(
                reverse('worksheet_detail', args=[section.worksheet_id]))
            self.assertEqual(response.status_code, 404)
            response = self.client.get(
                reverse('collection_edit', args=[section.pk]))
            self.assertEqual(response.status_code, 403)
        self.assertTrue(Collection.objects.filter(pk=section.pk).exists())
        self.assertEqual(Collection.objects.filter(parent=section).count(), 2)

    def test_visibility_and_publish_toggle(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        # Владелец видит, чужой учитель — нет; в «Моих листках» листка нет.
        response = self.client.get(reverse('worksheet_list'))
        self.assertNotContains(response, 'Проценты')
        response = self.client.get(
            reverse('collection_list'), {'source': collection.source_id},
            follow=True)
        self.assertContains(response, '6 класс')
        response = self.client.get(
            reverse('collection_detail', args=[collection.parent.pk]), follow=True)
        self.assertContains(response, 'Проценты')
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(reverse('collection_list'))
        self.assertNotContains(response, SOURCE_TITLE)
        self.assertEqual(self.client.get(
            reverse('collection_detail', args=[collection.pk])).status_code, 403)
        # Чужой не может опубликовать; владелец — может.
        response = self.client.post(
            reverse('collection_publish', args=[collection.pk]), {'published': '1'})
        self.assertEqual(response.status_code, 403)
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(
            reverse('collection_publish', args=[collection.pk]), {'published': '1'})
        collection.refresh_from_db()
        self.assertTrue(collection.is_published)
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('collection_detail', args=[collection.parent.pk]), follow=True)
        self.assertContains(response, 'Проценты')

    def test_section_page_hides_foreign_private_children(self):
        collection = move_to_collections(self.worksheet, self.teacher)
        self.client.login(username='teacher2', password='pass12345')
        published = make_worksheet(self.other, title='Открытая')
        published.grade = 6
        published.save()
        mine = move_to_collections(published, self.other)
        mine.is_published = True
        mine.save()
        response = self.client.get(
            reverse('collection_detail', args=[collection.parent.pk]), follow=True)
        self.assertContains(response, 'Открытая')
        self.assertNotContains(response, 'Проценты')

    def test_move_back_and_views(self):
        response = self.client.post(
            reverse('worksheet_to_collections', args=[self.worksheet.pk]))
        collection = Collection.objects.get(worksheet=self.worksheet)
        self.assertRedirects(
            response, reverse('collection_detail', args=[collection.pk]))
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(response, 'Вернуть в мои листки')
        response = self.client.post(
            reverse('collection_to_worksheets', args=[collection.pk]))
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertFalse(Collection.objects.filter(pk=collection.pk).exists())
        self.assertTrue(Worksheet.objects.filter(pk=self.worksheet.pk).exists())
        self.assertContains(self.client.get(reverse('worksheet_list')), 'Проценты')
        # Раздел вернуть нельзя, чужую подборку тоже.
        section = Collection.objects.get(locator='section:grade:6')
        with self.assertRaises(AuthoredError):
            move_to_worksheets(section)

    def test_bulk_move_from_worksheet_list(self):
        other_sheet = make_worksheet(self.teacher, title='Дроби')
        response = self.client.post(reverse('worksheet_bulk_update'), {
            'ids': [self.worksheet.pk, other_sheet.pk], 'to_collections': '1'})
        self.assertRedirects(response, reverse('worksheet_list'))
        self.assertEqual(Collection.objects.filter(
            worksheet__in=[self.worksheet, other_sheet]).count(), 2)
        self.assertEqual(
            Collection.objects.get(worksheet=other_sheet).parent.worksheet.title,
            'Разное')

    def test_management_command(self):
        out = StringIO()
        call_command('authored_to_collections', '--dry-run', stdout=out)
        self.assertIn('Проценты', out.getvalue())
        self.assertFalse(Collection.objects.filter(worksheet=self.worksheet).exists())
        call_command('authored_to_collections', stdout=out)
        self.assertTrue(Collection.objects.filter(worksheet=self.worksheet).exists())
        call_command('authored_to_collections', stdout=out)
        self.assertIn('Итого перенесено: 0', out.getvalue())


class CorpusPushTests(TestCase):
    def setUp(self):
        from problems.rubricator import seed_rubricator
        seed_rubricator()
        self.teacher = make_teacher()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch('worksheet_corpus.paths.OUTPUT_DIR', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_push_goes_to_collections(self):
        from worksheet_corpus.store import save_draft
        from .corpus import push_draft
        from .test_corpus import _sample_draft
        draft = _sample_draft()
        save_draft(draft)
        worksheet, info = push_draft(draft, self.teacher)
        self.assertIsNotNone(info['collection'])
        self.assertEqual(info['collection'].parent.worksheet.title, '6 класс')
        self.assertFalse(info['collection'].is_published)
        again, info2 = push_draft(draft, self.teacher)
        self.assertEqual(again.pk, worksheet.pk)
        self.assertEqual(Collection.objects.filter(worksheet=worksheet).count(), 1)


class AuthoredBrowserTests(TestCase):
    """Обзор авторских листков: группы по главной теме, виды, предпросмотр."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from problems.models import TaskTopic, Topic
        self.teacher = make_teacher()
        self.other = make_teacher('teacher2')
        algebra = Topic.objects.create(name='Алгебра', code='XAL', order=1)
        self.equations = Topic.objects.create(
            name='Уравнения', code='XAL.01', parent=algebra, order=1)
        self.inequalities = Topic.objects.create(
            name='Неравенства', code='XAL.02', parent=algebra, order=2)

        def make(title, topics=(), sheet_topics=(), grade=8, owner=None,
                 published=True, days_ago=0):
            worksheet = make_worksheet(owner or self.teacher, title=title,
                                       n_tasks=len(topics) or 1)
            worksheet.grade = grade
            worksheet.save()
            tasks = [item.task for item in worksheet.ordered_items()]
            for task, topic in zip(tasks, topics):
                TaskTopic.objects.create(
                    task=task, topic=topic, role=TaskTopic.ROLE_PRIMARY)
            for topic in sheet_topics:
                worksheet.topics.add(topic)
            collection = move_to_collections(worksheet, worksheet.owner)
            collection.is_published = published
            collection.save()
            Worksheet.objects.filter(pk=worksheet.pk).update(
                updated_at=timezone.now() - timedelta(days=days_ago))
            return collection

        eq, ineq = self.equations, self.inequalities
        # Большинство задач — «Уравнения».
        self.sheet10 = make('Листок 10', topics=(eq, eq, ineq), days_ago=5)
        # Поровну: решает первая тема листка — «Неравенства».
        self.sheet2 = make('Листок 2', topics=(eq, ineq),
                           sheet_topics=(ineq, eq), days_ago=1)
        self.plain = make('Разминка', days_ago=10)
        self.sheet9 = make('Квадратные', topics=(eq,), grade=9, days_ago=3)
        self.private = make('Чужой черновик', topics=(eq,), owner=self.other,
                            published=False)
        self.section = self.sheet10.parent
        self.client.login(username='teacher1', password='pass12345')

    def section_page(self, **params):
        return self.client.get(
            reverse('collection_detail', args=[self.section.pk]), params)

    def test_groups_by_main_topic_with_no_topic_last(self):
        from .authored_browser import group_sheets, load_sheets
        sheets = load_sheets(self.section.source, self.teacher, self.section)
        groups = group_sheets(sheets)
        self.assertEqual(
            [(g.label, [s.title for s in g.sheets]) for g in groups],
            [('Алгебра › Уравнения', ['Листок 10']),
             ('Алгебра › Неравенства', ['Листок 2']),
             ('Без темы', ['Разминка'])])
        by_title = {sheet.title: sheet for sheet in sheets}
        self.assertEqual(by_title['Листок 10'].tasks_total, 3)
        self.assertEqual(
            [info.topic.name for info in by_title['Листок 2'].other_topics],
            ['Уравнения'])

    def test_sorts_by_date_and_title(self):
        from .authored_browser import group_sheets, load_sheets
        sheets = load_sheets(self.section.source, self.teacher, self.section)
        [by_date] = group_sheets(sheets, 'date')
        self.assertIsNone(by_date.label)
        self.assertEqual([s.title for s in by_date.sheets],
                         ['Листок 2', 'Листок 10', 'Разминка'])
        [by_title] = group_sheets(sheets, 'title')
        self.assertEqual([s.title for s in by_title.sheets],
                         ['Листок 2', 'Листок 10', 'Разминка'])

    def test_section_page_lists_sheets_and_previews_first(self):
        response = self.section_page()
        self.assertTemplateUsed(response, 'worksheets/authored_browser.html')
        self.assertContains(response, 'Алгебра › Уравнения')
        self.assertContains(response, 'Без темы')
        self.assertNotContains(response, 'Квадратные')  # другой раздел
        self.assertNotContains(response, 'Чужой черновик')
        self.assertEqual(response.context['selected'].pk, self.sheet10.pk)
        self.assertFalse(response.context['explicit_sheet'])
        self.assertContains(response, 'Взять как листок')
        self.assertContains(response, 'Всё в корзину · 3')
        self.assertContains(response, 'Е.А. Мухин')
        self.assertContains(response, '3 листка')

    def test_sheet_param_renders_its_preview(self):
        response = self.section_page(sheet=self.plain.pk)
        self.assertTrue(response.context['explicit_sheet'])
        self.assertEqual(response.context['selected'].pk, self.plain.pk)
        self.assertContains(
            response, reverse('collection_detail', args=[self.plain.pk]))
        # Листок другого раздела или чужой черновик — не выбирается.
        for pk in (self.sheet9.pk, self.private.pk, 'x'):
            response = self.section_page(sheet=pk)
            self.assertEqual(response.context['selected'].pk, self.sheet10.pk)

    def test_selected_sheet_survives_sort_and_segments(self):
        response = self.section_page(sort='date', sheet=self.plain.pk)
        self.assertContains(
            response, f'<input type="hidden" name="sheet" value="{self.plain.pk}">',
            html=True)
        urls = {s['scope']: s['url'] for s in response.context['segments']}
        root = reverse('authored_collections')
        own = reverse('collection_detail', args=[self.section.pk])
        other = reverse('collection_detail', args=[self.sheet9.parent.pk])
        # Листок есть в корне и в своём разделе, в чужом разделе — нет.
        self.assertEqual(urls['all'], f'{root}?sort=date&sheet={self.plain.pk}')
        self.assertEqual(urls[str(self.section.pk)],
                         f'{own}?sort=date&sheet={self.plain.pk}')
        self.assertEqual(urls[str(self.sheet9.parent.pk)], f'{other}?sort=date')
        self.assertEqual(response.context['list_segment_url'],
                         f'{own}?sort=date&sheet={self.plain.pk}')
        self.assertContains(response, f'data-section-pk="{self.section.pk}"')
        # Без явного выбора поле не выводится, сегменты без sheet.
        response = self.section_page()
        self.assertNotContains(response, 'name="sheet"')
        self.assertEqual(response.context['segments'][0]['url'], root)

    def test_table_view_and_sorted_list(self):
        response = self.section_page(view='table')
        self.assertContains(response, 'также: Уравнения')
        self.assertContains(response, '>Взять</button>')
        self.assertIsNone(response.context['selected'])
        response = self.section_page(sort='date')
        self.assertEqual(
            [s.title for s in response.context['groups'][0].sheets],
            ['Листок 2', 'Листок 10', 'Разминка'])
        self.assertContains(response, f'?sort=date&amp;sheet={self.sheet2.pk}')

    def test_root_shows_all_sections(self):
        response = self.client.get(reverse('authored_collections'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sheets_total'], 4)
        self.assertContains(response, 'Квадратные')
        self.assertEqual([s['label'] for s in response.context['segments']],
                         ['Все', '8', '9'])
        response = self.client.get(
            reverse('collection_list'), {'source': self.section.source_id})
        self.assertRedirects(response, reverse('authored_collections'))

    def test_owner_sees_private_sheet(self):
        self.client.login(username='teacher2', password='pass12345')
        response = self.section_page()
        self.assertContains(response, 'Чужой черновик')
        self.assertContains(response, 'видна только вам')

    def test_preview_fragment_respects_visibility(self):
        url = reverse('collection_preview', args=[self.sheet2.pk])
        xhr = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        response = self.client.get(url, **xhr)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, 'base.html')
        self.assertContains(response, 'data-authored-head')
        self.assertContains(response, 'Листок 2')
        # Без XHR — обычная страница раздела с этим листком.
        self.assertRedirects(
            self.client.get(url),
            reverse('collection_detail', args=[self.section.pk])
            + f'?sheet={self.sheet2.pk}')
        # next уходит в «Всё в корзину», чужой хост — нет.
        response = self.client.get(url, {'next': '/collections/authored/?sheet=1'}, **xhr)
        self.assertContains(response, 'value="/collections/authored/?sheet=1"')
        response = self.client.get(url, {'next': 'https://evil.example/'}, **xhr)
        self.assertNotContains(response, 'evil.example')
        private = reverse('collection_preview', args=[self.private.pk])
        self.assertEqual(self.client.get(private, **xhr).status_code, 403)
        section = reverse('collection_preview', args=[self.section.pk])
        self.assertEqual(self.client.get(section, **xhr).status_code, 404)

    def test_query_count_does_not_grow_with_sheets(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        url = reverse('collection_detail', args=[self.section.pk])
        with CaptureQueriesContext(connection) as before:
            self.client.get(url, {'view': 'table'})
        for i in range(4):
            sheet = make_worksheet(self.teacher, title=f'Ещё {i}', n_tasks=3)
            sheet.grade = 8
            sheet.save()
            move_to_collections(sheet, self.teacher)
        with CaptureQueriesContext(connection) as after:
            response = self.client.get(url, {'view': 'table'})
        self.assertEqual(response.context['sheets_total'], 7)
        self.assertEqual(len(after), len(before))
