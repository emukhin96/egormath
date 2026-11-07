"""Счётчики каталога задач без DISTINCT и с кэшем
(``problems/catalog_counts.py``, аудит быстродействия 06.11.2026)."""
from django.core.cache import caches
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.permissions import catalog_tasks, visible_tasks
from worksheets.models import Worksheet, WorksheetItem

from .catalog_counts import CACHE_ALIAS, section_counts, subtree_count
from .models import Task, TaskTopic, Topic
from .test_permissions import Roles, shared_task
from .views import CatalogPaginator, filter_tasks


def link(task, topic, role=TaskTopic.ROLE_SECONDARY):
    TaskTopic.objects.create(task=task, topic=topic, role=role)


class SubtreeCountTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.root = Topic.objects.create(name='Тестовый раздел')
        self.child_a = Topic.objects.create(name='Уравнения', parent=self.root)
        self.child_b = Topic.objects.create(name='Неравенства', parent=self.root)
        self.other = Topic.objects.create(name='Другой раздел')
        self.both = shared_task(self.editor, 'В двух подтемах')
        link(self.both, self.child_a, TaskTopic.ROLE_PRIMARY)
        link(self.both, self.child_b)
        self.one = shared_task(self.editor, 'В одной подтеме')
        link(self.one, self.child_a, TaskTopic.ROLE_PRIMARY)
        self.elsewhere = shared_task(self.editor, 'В геометрии')
        link(self.elsewhere, self.other, TaskTopic.ROLE_PRIMARY)

    def test_task_with_two_topics_of_one_section_counted_once(self):
        catalog = catalog_tasks(self.editor)
        ids = [self.root.pk, self.child_a.pk, self.child_b.pk]
        self.assertEqual(subtree_count(catalog, ids), 2)
        self.assertEqual(subtree_count(catalog, [self.child_b.pk]), 1)
        self.assertEqual(subtree_count(catalog, [self.other.pk]), 1)
        # То же, что старый подсчёт через join и DISTINCT
        self.assertEqual(subtree_count(catalog, ids),
                         catalog.filter(topics__in=ids).distinct().count())

    def test_guest_sees_task_from_own_worksheet_once(self):
        # Приглашённый видит личную задачу автора подборки, стоящую в его
        # листке; без DISTINCT она не должна задвоиться ни в списке, ни в count()
        private = Task.new_for(self.editor, text_latex='Личная задача редактора')
        private.is_shared = False
        private.save(update_fields=['is_shared'])
        sheet = Worksheet.objects.create(title='Взятый листок', owner=self.guest)
        WorksheetItem.objects.create(worksheet=sheet, task=private, order=10)
        WorksheetItem.objects.create(worksheet=sheet, task=private, order=20)
        WorksheetItem.objects.create(worksheet=sheet, task=self.one, order=30)
        tasks = visible_tasks(self.guest)
        self.assertEqual(tasks.count(), len(list(tasks)))
        self.assertEqual(list(tasks.filter(pk=private.pk)), [private])
        self.assertIn(private, catalog_tasks(self.guest))
        self.assertNotIn(private, catalog_tasks(self.other_guest))

    def test_paginator_count_matches_distinct_results(self):
        self.client.login(username='editor', password='pass12345')
        params = {'topic': str(self.root.pk)}
        tasks = filter_tasks(params, self.editor)
        self.assertEqual(CatalogPaginator(tasks, 25).count, 2)
        self.assertEqual(CatalogPaginator(tasks, 25).count, len(list(tasks)))
        response = self.client.get(reverse('task_list'), params)
        self.assertEqual(response.context['page'].paginator.count, 2)
        root = next(t for t in response.context['topics'] if t.pk == self.root.pk)
        self.assertEqual(root.task_total, 2)
        self.assertEqual({c.name: c.task_total for c in root.children_visible},
                         {'Уравнения': 2, 'Неравенства': 1})


class CatalogCountsCacheTests(Roles, TransactionTestCase):
    """Вне транзакции (как в gunicorn) счётчики берутся из кэша и
    сбрасываются сигналами при правке задач."""

    def setUp(self):
        caches[CACHE_ALIAS].clear()
        self.make_users()
        self.root = Topic.objects.create(name='Тестовый раздел')
        self.task = shared_task(self.editor)
        link(self.task, self.root, TaskTopic.ROLE_PRIMARY)

    def tearDown(self):
        caches[CACHE_ALIAS].clear()

    def root_block(self, user=None):
        from .models import topic_tree
        from .views import _rubricator_blocks
        blocks = _rubricator_blocks(topic_tree(), user or self.editor)
        return next(b for b in blocks if b.pk == self.root.pk)

    def test_counts_cached_and_invalidated_by_task_changes(self):
        self.assertEqual(self.root_block().task_total, 1)
        with self.assertNumQueries(0):
            counts = section_counts(self.editor, [])
        self.assertEqual(counts[self.root.pk], 1)
        another = shared_task(self.editor, 'Новая')
        link(another, self.root, TaskTopic.ROLE_PRIMARY)
        self.assertEqual(self.root_block().task_total, 2)
        TaskTopic.objects.filter(task=another).delete()
        self.assertEqual(self.root_block().task_total, 1)
        another.delete()
        self.assertEqual(self.root_block().task_total, 1)

    def test_bulk_topic_add_and_guest_worksheet_invalidate(self):
        # topics.add() создаёт связки bulk_create без post_save (ревью #318)
        another = shared_task(self.editor, 'Через add')
        self.assertEqual(self.root_block().task_total, 1)
        another.topics.add(self.root)
        self.assertEqual(self.root_block().task_total, 2)
        # У приглашённого база каталога зависит от состава его листков
        private = Task.new_for(self.editor, text_latex='Личная редактора')
        private.is_shared = False
        private.save(update_fields=['is_shared'])
        link(private, self.root, TaskTopic.ROLE_PRIMARY)
        self.assertEqual(self.root_block(self.guest).task_total, 2)
        sheet = Worksheet.objects.create(title='Взятый листок', owner=self.guest)
        item = WorksheetItem.objects.create(worksheet=sheet, task=private, order=10)
        self.assertEqual(self.root_block(self.guest).task_total, 3)
        item.delete()
        self.assertEqual(self.root_block(self.guest).task_total, 2)

    def test_counts_separate_for_teachers(self):
        own = Task.new_for(self.guest, text_latex='Личная гостя')
        link(own, self.root, TaskTopic.ROLE_PRIMARY)
        self.assertEqual(self.root_block().task_total, 1)
        self.assertEqual(self.root_block(self.guest).task_total, 2)
