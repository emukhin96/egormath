"""Доски: блок «Задание · ответ ученика» в диалоге и панель «Условия задач»."""
import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment, Submission, SubmissionPart
from problems.models import Task, TaskSubitem
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet


class BoardsPeekBase(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher, n_tasks=0)
        self.task = Task.objects.create(text_latex='Найдите корень уравнения $2x=8$',
                                        answer_mask='{{number: 4}}', author_answer_latex='$4$')
        self.item = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=1)
        self.assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student, assigned_by=self.teacher)
        self.client.force_login(self.teacher)

    def peek(self, task=None, assignment=None, worksheet=None):
        return self.client.get(reverse('worksheet_boards_peek', args=[
            (worksheet or self.worksheet).pk, (assignment or self.assignment).pk, (task or self.task).pk]))

    def answer(self, value, check, task=None):
        return Submission.objects.create(
            assignment=self.assignment, task=task or self.task, answer_json={'s1': value},
            auto_check=check, check_json={'s1': check}, checked_at=timezone.now())


class BoardsPeekFragmentTests(BoardsPeekBase):
    def test_condition_answer_reference_and_review_link(self):
        self.answer('5', Submission.CHECK_WRONG)
        response = self.peek()
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('Задание №1 · ответ ученика', html)
        self.assertIn('Найдите корень уравнения', html)
        # ответ ученика по маске с отметкой слота и итог в заголовке
        self.assertIn('data-status="wrong"', html)
        self.assertIn('✗ неверно', html)
        # эталон — под отдельным свёрнутым «Эталон», не рядом с ответом
        self.assertIn('<summary>Эталон</summary>', html)
        self.assertNotIn('review-reference', html)
        self.assertIn(reverse('review_assignment', args=[self.assignment.pk]) + '#task-1', html)
        # блок свёрнут по умолчанию: атрибута open нет
        self.assertNotIn('<details class="boards-peek" data-peek data-version="" open', html)

    def test_status_without_answer_and_correct(self):
        self.assertContains(self.peek(), 'нет ответа')
        self.answer('4', Submission.CHECK_OK)
        self.assertContains(self.peek(), '✓ верно')

    def test_rights(self):
        other = make_teacher('teacher2')
        self.client.force_login(other)
        self.assertEqual(self.peek().status_code, 404)
        self.client.force_login(self.teacher)
        stranger = Task.objects.create(text_latex='Не из листка')
        self.assertEqual(self.peek(task=stranger).status_code, 404)
        foreign_ws = make_worksheet(self.teacher, title='Другой', n_tasks=0)
        self.assertEqual(self.peek(worksheet=foreign_ws).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.peek().status_code, 403)

    def test_only_selected_subitems_of_item(self):
        task = Task.objects.create(text_latex='Вычислите')
        first = TaskSubitem.objects.create(task=task, order=1, text_latex='первый пункт', answer_mask='{{number: 1}}',
                                           author_answer_latex='$1$')
        second = TaskSubitem.objects.create(task=task, order=2, text_latex='второй пункт', answer_mask='{{number: 2}}',
                                            author_answer_latex='$222$')
        item = WorksheetItem.objects.create(worksheet=self.worksheet, task=task, order=2, all_subitems=False)
        item.subitems.set([second])
        submission = Submission.objects.create(assignment=self.assignment, task=task)
        SubmissionPart.objects.create(submission=submission, subitem=second, answer_json={'s1': '2'},
                                      auto_check=Submission.CHECK_OK, check_json={'s1': 'ok'},
                                      checked_at=timezone.now())
        html = self.peek(task=task).content.decode()
        self.assertIn('Задание №2', html)
        self.assertIn('второй пункт', html)
        self.assertNotIn('первый пункт', html)
        self.assertIn('$222$', html)
        self.assertNotIn('$1$', html)
        # единственный выбранный подпункт отвечен верно — «верно», а не «частично»
        self.assertIn('✓ верно', html)
        self.assertNotIn(first.text_latex, html)

    def test_local_copy_of_task(self):
        copy = self.task.make_variant(self.teacher)
        copy.text_latex = 'Локальная версия условия'
        copy.save()
        self.item.task = copy
        self.item.save()
        html = self.peek(task=copy).content.decode()
        self.assertIn('Локальная версия условия', html)
        self.assertEqual(self.peek(task=self.task).status_code, 404)

    def test_hidden_item(self):
        self.assignment.hidden_items.add(self.item)
        response = self.peek()
        self.assertContains(response, 'задача скрыта у ученика')
        self.assertNotContains(response, 'Открыть в проверке')

    def test_live_answers_change_only_with_answer(self):
        live = reverse('worksheet_boards_live', args=[self.worksheet.pk])
        self.assertEqual(self.client.get(live).json()['answers'], [])
        submission = self.answer('5', Submission.CHECK_WRONG)
        first = self.client.get(live).json()['answers']
        self.assertEqual([(a['assignment'], a['task']) for a in first], [(self.assignment.pk, self.task.pk)])
        # версия в живом опросе совпадает с версией во фрагменте
        self.assertIn('data-version="%s"' % first[0]['version'], self.peek().content.decode())
        # доска ученика не меняет версию ответа
        self.client.force_login(self.student)
        self.client.post(reverse('canvas:save', args=[self.assignment.pk, self.task.pk, 1]),
                         data=json.dumps({'layer': 'student', 'version': 0, 'background': 'grid', 'elements': [
                             {'id': 'a1', 't': 'path', 'c': '#1d4ed8', 'w': 4, 'p': [[1, 1], [2, 2]]}]}),
                         content_type='application/json')
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(live).json()['answers'], first)
        submission.answer_json = {'s1': '4'}
        submission.auto_check = Submission.CHECK_OK
        submission.save()
        self.assertNotEqual(self.client.get(live).json()['answers'], first)


class BoardsConditionsPanelTests(BoardsPeekBase):
    def tasks_url(self, **params):
        url = reverse('worksheet_boards_tasks', args=[self.worksheet.pk])
        return url, params

    def get(self, **params):
        url, params = self.tasks_url(**params)
        return self.client.get(url, params)

    def add_tasks(self, count, start=2):
        tasks = []
        for i in range(count):
            task = Task.objects.create(text_latex=f'Условие задачи {start + i}', author_answer_latex=f'${start + i}$')
            TaskSubitem.objects.create(task=task, order=1, text_latex=f'подпункт {start + i}')
            WorksheetItem.objects.create(worksheet=self.worksheet, task=task, order=start + i)
            tasks.append(task)
        return tasks

    def test_page_has_toggle_and_lazy_panel(self):
        response = self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk]), {'task': self.task.pk})
        self.assertContains(response, 'data-peek-panel-toggle')
        self.assertContains(response, 'Условия задач')
        # условия не рендерятся со страницей — только адрес фрагмента с тем же фильтром
        self.assertNotContains(response, 'Найдите корень уравнения')
        self.assertContains(response, 'data-url="%s?task=%d"' % (
            reverse('worksheet_boards_tasks', args=[self.worksheet.pk]), self.task.pk))
        self.assertContains(response, 'data-peek-url="%s"' % reverse(
            'worksheet_boards_peek', args=[self.worksheet.pk, 0, 0]))

    def test_all_tasks_in_order_with_reference(self):
        WorksheetItem.objects.create(worksheet=self.worksheet, order=2, text_latex='Текстовый блок')
        second, third = self.add_tasks(2, start=3)
        html = self.get().content.decode()
        positions = [html.index(text) for text in ('Найдите корень уравнения', 'Условие задачи 3', 'Условие задачи 4')]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('Текстовый блок', html)
        self.assertEqual(html.count('<summary>Эталон</summary>'), 3)
        self.assertIn('<span class="ws-num">3.</span>', html)
        self.assertIn(reverse('worksheet_boards', args=[self.worksheet.pk]) + '?task=%d' % third.pk, html)
        self.assertNotIn('is-current', html)

    def test_selected_task_highlighted_and_group_kept(self):
        _, third = self.add_tasks(2)
        from accounts.models import StudentGroup
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        html = self.get(task=third.pk, group=group.pk).content.decode()
        self.assertEqual(html.count('is-current'), 1)
        self.assertIn('class="boards-peek-task is-current" id="boards-peek-task-%d"' % third.pk, html)
        self.assertIn('?group=%d&amp;task=%d' % (group.pk, third.pk), html)

    def test_rights(self):
        self.client.force_login(make_teacher('teacher2'))
        self.assertEqual(self.get().status_code, 404)

    def test_no_n_plus_one(self):
        self.add_tasks(2)
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(self.get().status_code, 200)
        self.add_tasks(10, start=10)
        with CaptureQueriesContext(connection) as large:
            self.assertEqual(self.get().status_code, 200)
        self.assertEqual(len(large), len(small))
        self.assertLessEqual(len(large), 15)
