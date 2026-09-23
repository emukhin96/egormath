"""Общий поиск задач (finder) и быстрая задача в конструкторе."""
from django.test import TestCase
from django.urls import reverse

from problems.models import Task, Topic
from problems.tests import make_teacher
from worksheets.tests import make_worksheet


XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class FinderTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.worksheet = make_worksheet(self.teacher)
        self.worksheet.grade = 8
        self.worksheet.save()
        self.topic = Topic.objects.create(name='Уравнения', code='EQ')
        self.worksheet.topics.add(self.topic)
        self.task = Task.objects.create(
            text_latex='Найдите корни $x^2=4$.', created_by=self.teacher)

    def test_catalog_search_by_id(self):
        response = self.client.get(reverse('task_list'), {'q': f'#{self.task.pk}'})
        self.assertEqual(list(response.context['page'].object_list), [self.task])
        response = self.client.get(reverse('task_list'), {'q': str(self.task.pk)})
        self.assertEqual(list(response.context['page'].object_list), [self.task])
        self.assertContains(response, 'data-finder-target="results"')
        self.assertContains(response, 'data-finder')

    def test_builder_search_and_xhr_add(self):
        url = reverse('worksheet_detail', args=[self.worksheet.pk])
        response = self.client.get(url, {'q': 'корни'})
        self.assertEqual(response.context['found_tasks'], [self.task])
        self.assertContains(response, 'id="finder-results"')
        self.assertContains(response, 'data-finder-anchor="add-tasks"')

        response = self.client.post(
            reverse('worksheet_add_task', args=[self.worksheet.pk]),
            {'task_id': self.task.pk}, **XHR)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['outcome'], 'added')
        self.assertTrue(self.worksheet.items.filter(task=self.task).exists())
        response = self.client.post(
            reverse('worksheet_add_task', args=[self.worksheet.pk]),
            {'task_id': self.task.pk}, **XHR)
        self.assertEqual(response.json()['outcome'], 'exists')
        # Найденная задача уже в листке — в результатах её больше нет.
        response = self.client.get(url, {'q': 'корни'})
        self.assertEqual(response.context['found_tasks'], [])

    def test_quick_task_creates_and_appends(self):
        url = reverse('worksheet_quick_task', args=[self.worksheet.pk])
        response = self.client.post(url, {
            'text_latex': 'Вычислите $2+2$.', 'answer_latex': '4',
            'solution_latex': 'Складываем.', 'stars': '2'}, **XHR)
        self.assertEqual(response.status_code, 200, response.content)
        task = Task.objects.get(text_latex='Вычислите $2+2$.')
        self.assertEqual((task.answer_latex, task.solution_latex, task.stars),
                         ('4', 'Складываем.', 2))
        self.assertEqual(task.grade_level, 8)
        self.assertEqual(list(task.topics.all()), [self.topic])
        self.assertEqual(task.created_by, self.teacher)
        self.assertEqual(self.worksheet.ordered_items().last().task, task)
        # Пустое условие и дубликат отклоняются без создания задачи.
        response = self.client.post(url, {'text_latex': '  '}, **XHR)
        self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {'text_latex': 'Вычислите $2+2$.'}, **XHR)
        self.assertEqual(response.status_code, 400)
        self.assertIn(f'#{task.pk}', response.json()['message'])
        self.assertEqual(Task.objects.filter(text_latex='Вычислите $2+2$.').count(), 1)
        # Без JS — redirect в конструктор.
        response = self.client.post(url, {'text_latex': 'Ещё одна.'})
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))

    def test_foreign_worksheet_is_forbidden(self):
        other = make_teacher('teacher2')
        foreign = make_worksheet(other)
        response = self.client.post(
            reverse('worksheet_quick_task', args=[foreign.pk]),
            {'text_latex': 'Чужое.'})
        self.assertEqual(response.status_code, 404)
