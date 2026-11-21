"""Крошки карточки задачи: «Задачи › источник › подборка» (problems/source_trail.py)."""
from django.test import TestCase
from django.urls import reverse

from problems.models import Source, Task, TaskSource
from problems.tests import make_teacher
from worksheets.collection_pages import PLAIN_PAGE_SIZE
from worksheets.models import Collection, Worksheet, WorksheetItem


class SourceTrailTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Задачник Иванова')
        root_sheet = Worksheet.objects.create(title='Глава 1. Уравнения', owner=self.owner)
        self.root = Collection.objects.create(
            worksheet=root_sheet, source=self.source, locator='g1',
            source_path=['Глава 1'], is_published=True)
        leaf_sheet = Worksheet.objects.create(title='§ 2. Линейные', owner=self.owner)
        self.leaf = Collection.objects.create(
            worksheet=leaf_sheet, source=self.source, parent=self.root,
            locator='g1-p2', source_path=['Глава 1', '§ 2'], is_published=True)
        self.tasks = []
        for number in range(1, PLAIN_PAGE_SIZE + 4):
            task = Task.objects.create(text_latex=f'Задача {number}.', created_by=self.owner)
            TaskSource.objects.create(task=task, source=self.source, number=str(number))
            WorksheetItem.objects.create(worksheet=leaf_sheet, task=task, order=number * 10)
            self.tasks.append(task)

    def test_card_crumbs_lead_to_source_and_collection(self):
        task = self.tasks[-1]
        response = self.client.get(reverse('task_detail', args=[task.pk]))
        self.assertEqual(response.status_code, 200)
        source_url = f'{reverse("collection_list")}?source={self.source.pk}'
        place = f'{reverse("collection_detail", args=[self.leaf.pk])}?task={task.pk}#task-{task.pk}'
        self.assertContains(response, f'href="{source_url}"')
        self.assertContains(response, f'href="{reverse("collection_detail", args=[self.root.pk])}"')
        # Последняя крошка и ссылка источника в мета-строке — сразу к задаче
        self.assertContains(response, f'href="{place}"', count=2)

    def test_collection_opens_page_with_task(self):
        task = self.tasks[-1]
        response = self.client.get(
            reverse('collection_detail', args=[self.leaf.pk]), {'task': task.pk})
        self.assertEqual(response.context['page'].number, 2)
        self.assertContains(response, f'id="task-{task.pk}"')
        first = self.client.get(reverse('collection_detail', args=[self.leaf.pk]))
        self.assertEqual(first.context['page'].number, 1)

    def test_hidden_collection_gives_plain_source(self):
        self.leaf.is_published = False
        self.leaf.save(update_fields=['is_published'])
        other = make_teacher('teacher2')
        task = self.tasks[0]
        task.is_shared = True
        task.save(update_fields=['is_shared'])
        self.client.force_login(other)
        response = self.client.get(reverse('task_detail', args=[task.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'?task={task.pk}#task-')
        self.assertNotContains(response, f'?source={self.source.pk}"')
        self.assertContains(response, '<span>Задачник Иванова, № 1</span>', html=True)
