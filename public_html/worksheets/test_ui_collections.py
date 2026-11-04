"""Подборки и авторские листки без дублей в панели (ревизия 03.11, P1, P3)."""
from django.test import TestCase
from django.urls import reverse

from problems.models import Source
from problems.models import Task
from problems.tests import make_teacher
from worksheets.models import Collection
from worksheets.models import Worksheet
from worksheets.models import WorksheetItem

from .test_authored import AuthoredBrowserTests


class CollectionPanelTests(TestCase):
    def setUp(self):
        owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Задачник')
        worksheet = Worksheet.objects.create(title='Глава', owner=owner)
        task = Task.objects.create(text_latex='Вычислите', created_by=owner)
        WorksheetItem.objects.create(worksheet=worksheet, task=task, order=10)
        self.collection = Collection.objects.create(
            worksheet=worksheet, source=self.source, locator='ch-1', is_published=True)

    def test_source_list_not_in_panel(self):
        response = self.client.get(reverse('collection_list'))
        self.assertNotContains(response, 'Доступные источники')
        # Без выбранного источника панель пустая — base.html её скрывает
        self.assertNotContains(response, 'sidebar-section')
        self.assertContains(response, f'?source={self.source.pk}')

    def test_source_and_detail_keep_navigation(self):
        response = self.client.get(reverse('collection_list'), {'source': self.source.pk})
        self.assertContains(response, 'Структура источника')
        self.assertContains(response, 'Все источники')
        detail = self.client.get(reverse('collection_detail', args=[self.collection.pk]))
        self.assertContains(detail, 'Структура источника')
        self.assertNotContains(detail, 'Доступные источники')


class AuthoredPanelTests(TestCase):
    setUp = AuthoredBrowserTests.setUp

    def test_no_panel_topics_above_list_view_in_menu(self):
        html = self.client.get(reverse('authored_collections')).content.decode()
        self.assertNotIn('sidebar-section', html)
        topics = html.split('data-authored-topic-menu', 1)[1].split('</details>', 1)[0]
        self.assertIn('data-authored-topic=""', topics)
        self.assertIn('Алгебра › Уравнения', topics)
        actions = html.split('<div class="page-actions">', 1)[1].split('</details>', 1)[0]
        self.assertIn('more-menu is-head', actions)
        self.assertIn('Вид: таблица', actions)
        self.assertIn('data-sheet-scope="all"', actions)
        self.assertNotIn('<nav class="seg" aria-label="Вид">', html)

    def test_topic_links_switch_to_topic_sort(self):
        html = self.client.get(reverse('authored_collections'), {'sort': 'date'}).content.decode()
        topics = html.split('data-authored-topic-menu', 1)[1].split('</details>', 1)[0]
        # При сортировке по дате групп тем на странице нет: ссылка ведёт на вид по темам
        self.assertIn(f'href="{reverse("authored_collections")}#', topics)
