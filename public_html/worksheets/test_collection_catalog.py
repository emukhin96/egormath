"""Дерево каталога подборок из кэша (``worksheets/collection_catalog.py``,
аудит быстродействия 06.11.2026)."""
from django.core.cache import caches
from django.test import TransactionTestCase
from django.urls import reverse

from problems.models import Source, Task, Topic
from problems.tests import make_teacher

from .collection_catalog import CACHE_ALIAS, catalog_nodes, collection_catalog
from .models import Collection, Worksheet, WorksheetItem


class CollectionCatalogCacheTests(TransactionTestCase):
    """Вне транзакции (как в gunicorn) узлы берутся из кэша и сбрасываются
    сигналами при правке подборок, их листков, элементов и тем."""

    def setUp(self):
        caches[CACHE_ALIAS].clear()
        self.owner = make_teacher()
        self.other = make_teacher('teacher2')
        self.source = Source.objects.create(title='Задачник')
        self.worksheet = Worksheet.objects.create(title='№3. Готовая тема', owner=self.owner)
        self.task = Task.objects.create(text_latex='Вычислите $2+2$.', created_by=self.owner)
        WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=10)
        self.collection = Collection.objects.create(
            worksheet=self.worksheet, source=self.source, locator='chapter-1',
            is_published=True)

    def tearDown(self):
        caches[CACHE_ALIAS].clear()

    def row(self, user):
        groups = collection_catalog(user)
        group = next((g for g in groups if g['source'].pk == self.source.pk), None)
        return group['rows'][0] if group else None

    def test_tree_served_from_cache_until_collection_changes(self):
        row = self.row(self.owner)
        self.assertEqual(row['collection'].catalog_title, '№03. Готовая тема')
        self.assertEqual(row['item_total'], 1)
        with self.assertNumQueries(0):
            catalog_nodes()
        # Элемент листка: число задач растёт сразу
        WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=20)
        self.assertEqual(self.row(self.owner)['item_total'], 2)
        # Тема листка попадает в дерево
        topic = Topic.objects.create(name='Тестовая тема каталога')
        self.worksheet.topics.add(topic)
        self.assertEqual([t.pk for t in self.row(self.owner)['topics']], [topic.pk])
        # Название листка
        self.worksheet.title = 'Другое название'
        self.worksheet.save()
        self.assertEqual(self.row(self.owner)['collection'].catalog_title, 'Другое название')
        # Снятие с публикации прячет подборку от другого учителя, у владельца остаётся
        self.collection.is_published = False
        self.collection.save()
        self.assertIsNone(self.row(self.other))
        self.assertIsNotNone(self.row(self.owner))
        self.collection.delete()
        self.assertIsNone(self.row(self.owner))

    def test_visibility_is_computed_per_user_from_shared_nodes(self):
        private_sheet = Worksheet.objects.create(title='Личная', owner=self.owner)
        WorksheetItem.objects.create(worksheet=private_sheet, task=self.task, order=10)
        Collection.objects.create(worksheet=private_sheet, source=self.source,
                                  locator='private', parent=self.collection)
        self.assertEqual(self.row(self.owner)['item_total'], 2)
        self.assertEqual(self.row(self.other)['item_total'], 1)
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(reverse('collection_list'), {'source': self.source.pk})
        self.assertContains(response, '<strong>1</strong> задача', html=True)
        self.assertNotContains(response, 'Личная')
