"""Страница «задача у класса» (макет D_Task, assignments/windows.task_class):
ответы группами, полоса прогресса, режим без имён, входы с карты и из окна."""
from django.test import TestCase
from django.urls import reverse

from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .models import Assignment, Submission, SubmissionCheckAttempt


class TaskClassTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.filter(worksheet=self.worksheet).delete()
        self.task = Task.objects.create(text_latex='Найдите площадь', answer_mask='S = {{number: 30}}')
        self.item = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=1)
        self.url = reverse('assignment_item_class', args=[self.worksheet.pk, self.item.pk])
        answers = [('anna', 'Белова', '30', ['ok']), ('ilya', 'Громов', '30', ['wrong', 'ok']),
                   ('oleg', 'Жуков', '23', ['wrong']), ('dasha', 'Ким', '23', ['wrong', 'wrong']),
                   ('petr', 'Фомин', '2', ['wrong']), ('nika', 'Морозова', None, [])]
        for username, last, value, results in answers:
            student = make_student(self.teacher, username=username)
            student.last_name = last
            student.save()
            assignment = Assignment.objects.create(worksheet=self.worksheet, student=student, assigned_by=self.teacher)
            if value is None:
                continue
            sub = Submission.objects.create(assignment=assignment, task=self.task, answer_json={'s1': value})
            for number, result in enumerate(results, 1):
                SubmissionCheckAttempt.objects.create(submission=sub, number=number, result=result,
                                                      snapshot={'targets': [{'kind': 'task', 'id': self.task.pk, 'answer': f'S = {value}', 'result': result}]})
        Submission.objects.filter(answer_json={'s1': '2'}).update(updated_at=Submission.objects.first().updated_at.replace(year=2025))
        self.client.force_login(self.teacher)

    def test_groups_and_progress(self):
        response = self.client.get(self.url)
        groups = response.context['answer_groups']
        self.assertEqual([(g['kind'], g['verdict'], len(g['rows'])) for g in groups],
                         [('ok', 'Верно', 2), ('wrong', 'Неверно, частая ошибка', 2), ('wrong', 'Неверно', 1), ('rest', 'ответа на эту задачу нет', 1)])
        self.assertEqual({b['key']: b['count'] for b in response.context['bar']},
                         {'ok_first': 1, 'ok_later': 1, 'wrong': 3, 'live': 0, 'rest': 1})
        self.assertEqual(response.context['tries'], [(1, 1), (2, 1)])
        self.assertContains(response, 'Петя Белова')
        self.assertContains(response, 'Прогресс по задаче')
        self.assertContains(response, reverse('task_attempts', args=[Assignment.objects.get(student__username='oleg').pk, self.task.pk]))
        self.assertNotContains(response, '·')
        fragment = self.client.get(self.url, {'fragment': '1'})
        self.assertTemplateUsed(fragment, 'assignments/_task_class_body.html')
        self.assertNotContains(fragment, 'fragment=1')

    def test_anonymous(self):
        response = self.client.get(self.url, {'anon': '1'})
        self.assertNotContains(response, 'Петя Белова')
        self.assertContains(response, 'Ученик 1')
        self.assertNotContains(response, 'data-attempt-url="/assignments/')
        self.assertContains(response, 'Показать имена')

    def test_entry_points(self):
        progress = self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk]))
        self.assertContains(progress, self.url)
        window = self.client.get(reverse('worksheet_task_window', args=[self.worksheet.pk, self.item.pk]))
        self.assertContains(window, 'Открыть у всего класса')
        self.assertContains(window, self.url)
        other = WorksheetItem.objects.create(worksheet=make_worksheet(self.teacher), task=self.task, order=1)
        self.assertEqual(self.client.get(reverse('assignment_item_class', args=[self.worksheet.pk, other.pk])).status_code, 404)
