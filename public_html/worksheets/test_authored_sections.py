"""Авторские листки: «листалка» разделов рубрикатора и тема листка разделом."""
from django.test import TestCase
from django.urls import reverse

from problems.models import TaskTopic
from problems.models import Topic
from problems.tests import make_teacher
from worksheets.tests import make_worksheet

from .authored import move_to_collections


class AuthoredRootSectionsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.algebra = Topic.objects.create(name='Алгебра', code='XAL', order=1)
        self.equations = Topic.objects.create(
            name='Уравнения', code='XAL.01', parent=self.algebra, order=1)
        self.geometry = Topic.objects.create(name='Геометрия', code='XGE', order=2)
        self.triangles = Topic.objects.create(
            name='Треугольники', code='XGE.01', parent=self.geometry, order=1)

        def make(title, task_topic=None, sheet_topic=None):
            worksheet = make_worksheet(self.teacher, title=title, n_tasks=1)
            worksheet.grade = 8
            worksheet.save()
            if task_topic:
                TaskTopic.objects.create(
                    task=worksheet.ordered_items()[0].task, topic=task_topic,
                    role=TaskTopic.ROLE_PRIMARY)
            if sheet_topic:
                worksheet.topics.add(sheet_topic)
            collection = move_to_collections(worksheet, self.teacher)
            collection.is_published = True
            collection.save()
            return collection

        # Геометрия создана раньше, но в дереве идёт после алгебры.
        self.tri = make('Треугольники', task_topic=self.triangles)
        self.eq = make('Уравнения', task_topic=self.equations)
        # Тема листка — раздел целиком, у задач тем нет.
        self.alg = make('Повторение алгебры', sheet_topic=self.algebra)
        self.plain = make('Разминка')
        self.section = self.eq.parent
        self.client.login(username='teacher1', password='pass12345')

    def test_root_sections_in_tree_order_with_counts(self):
        from .authored_browser import load_sheets, root_sections
        sheets = load_sheets(self.section.source, self.teacher, self.section)
        self.assertEqual(
            [(row.topic.name, row.sheets_total) for row in root_sections(sheets)],
            [('Алгебра', 2), ('Геометрия', 1)])
        by_title = {sheet.title: sheet for sheet in sheets}
        self.assertEqual(by_title['Повторение алгебры'].main_topic.root_pk,
                         self.algebra.pk)
        self.assertEqual(by_title['Уравнения'].main_topic.root_pk,
                         self.algebra.pk)
        self.assertIsNone(by_title['Разминка'].main_topic)

    def test_page_has_sections_bar_and_rows_know_their_section(self):
        response = self.client.get(
            reverse('collection_detail', args=[self.section.pk]))
        self.assertContains(response, 'data-authored-roots')
        self.assertContains(response, 'Все разделы')
        self.assertContains(
            response, f'href="#section-{self.geometry.pk}" '
            f'data-authored-root="{self.geometry.pk}"')
        self.assertContains(
            response, f'data-authored-row data-root="{self.algebra.pk}"', count=2)
        self.assertContains(
            response, f'data-root="{self.geometry.pk}"', count=2)  # строка и тема меню
        # Таблица — те же атрибуты у строк.
        table = self.client.get(
            reverse('collection_detail', args=[self.section.pk]),
            {'view': 'table'})
        self.assertContains(
            table, f'data-authored-row data-root="{self.geometry.pk}"')

    def test_one_section_hides_the_bar(self):
        self.tri.delete()
        response = self.client.get(
            reverse('collection_detail', args=[self.section.pk]))
        self.assertNotContains(response, 'data-authored-roots')


class WorksheetBranchTopicTests(TestCase):
    """Листку можно назначить раздел рубрикатора без конкретной темы."""

    def setUp(self):
        self.teacher = make_teacher()
        self.algebra = Topic.objects.create(name='Алгебра', code='XAL', order=1)
        Topic.objects.create(
            name='Уравнения', code='XAL.01', parent=self.algebra, order=1)
        self.worksheet = make_worksheet(self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def test_quick_update_accepts_section(self):
        response = self.client.post(
            reverse('worksheet_quick_update', args=[self.worksheet.pk]),
            {'topics': [self.algebra.pk], 'topics_submitted': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.worksheet.topics.all()), [self.algebra])

    def test_form_picker_allows_branches(self):
        response = self.client.get(
            reverse('worksheet_edit', args=[self.worksheet.pk]))
        self.assertContains(response, 'data-branches="1"')
        self.assertNotContains(response, '{#')  # комментарий шаблона не в HTML

    def test_quick_task_inherits_only_leaf_topics(self):
        equations = Topic.objects.get(code='XAL.01')
        self.worksheet.topics.set([self.algebra, equations])
        self.client.post(
            reverse('worksheet_quick_task', args=[self.worksheet.pk]),
            {'text_latex': 'Решите уравнение $x^2=49$.'})
        task = self.worksheet.ordered_items().last().task
        self.assertEqual(list(task.topics.all()), [equations])
        # Раздел без подтемы — задача остаётся без темы.
        self.worksheet.topics.set([self.algebra])
        self.client.post(
            reverse('worksheet_quick_task', args=[self.worksheet.pk]),
            {'text_latex': 'Решите неравенство $x>3$.'})
        task = self.worksheet.ordered_items().last().task
        self.assertFalse(task.topics.exists())
