"""Подборка: карточка задачи, ответ одной задачи, тумблер «решения» (19.11)."""
from django.test import TestCase
from django.urls import reverse

from problems.models import Source
from problems.models import Task
from problems.tests import make_teacher
from worksheets.models import Collection
from worksheets.models import Worksheet
from worksheets.models import WorksheetItem


class CollectionAnswersTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.worksheet = Worksheet.objects.create(title='Вариант 5', owner=self.owner)
        self.collection = Collection.objects.create(
            worksheet=self.worksheet, source=Source.objects.create(title='Задачник'),
            locator='v-5', is_published=True)

    def add_task(self, order, **fields):
        task = Task.objects.create(text_latex='Найдите $x$', created_by=self.owner, **fields)
        WorksheetItem.objects.create(worksheet=self.worksheet, task=task, order=order)
        return task

    def get_html(self):
        return self.client.get(
            reverse('collection_detail', args=[self.collection.pk])).content.decode()

    def test_task_card_link_and_answer_button(self):
        task = self.add_task(10, author_answer_latex='19')
        bare = self.add_task(20)
        html = self.get_html()
        # #id ведёт на карточку задачи — там свойства и правка
        self.assertIn(f'href="{reverse("task_detail", args=[task.pk])}"', html)
        self.assertIn(f'>#{task.pk}</a>', html)
        self.assertIn(f'>#{bare.pk}</a>', html)
        # Кнопка «ответ» — только у задачи, где есть что показать
        self.assertEqual(html.count('data-answer-peek'), 1)
        self.assertIn('aria-pressed="false"', html)

    def test_solutions_toggle_only_with_solutions(self):
        self.add_task(10, author_answer_latex='19')
        html = self.get_html()
        self.assertNotIn('id="toggle-solutions"', html)
        self.assertIn('collection-view-options is-sticky', html)

        self.add_task(20, author_answer_latex='45',
                      author_solution_latex='Объём конуса в четыре раза меньше.')
        html = self.get_html()
        self.assertIn('id="toggle-solutions"', html)
        self.assertIn('data-storage-key="collection-show-solutions"', html)
        # У задачи с ответом и решением кнопка раскрывает оба
        self.assertIn('>ответ и решение</button>', html)
