"""Окна карты ответов: «задача» (D_TaskView) и «задача у ученика»
(D_AnswerView), комментарий без смены оценки (assignments/windows.py)."""
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from problems.models import Task
from problems.tests import make_student, make_teacher
from workaudit.models import ActivityEvent
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .models import Assignment, Review, Submission, SubmissionCheckAttempt


class TaskWindowsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.filter(worksheet=self.worksheet).delete()
        self.tasks = [Task.objects.create(text_latex=f'Найдите отрезок {n}', answer_mask='MB = {{number: 18}}') for n in (1, 2)]
        self.items = [WorksheetItem.objects.create(worksheet=self.worksheet, task=t, order=n) for n, t in enumerate(self.tasks, 1)]
        self.assignments = []
        for username, last in [('anna', 'Белова'), ('oleg', 'Жуков')]:
            student = make_student(self.teacher, username=username)
            student.last_name = last
            student.save()
            self.assignments.append(Assignment.objects.create(worksheet=self.worksheet, student=student, assigned_by=self.teacher))
        self.anna, self.oleg = self.assignments
        for assignment, value, result in [(self.anna, '18', 'ok'), (self.oleg, '23', 'wrong')]:
            sub = Submission.objects.create(assignment=assignment, task=self.tasks[0], answer_json={'s1': value})
            SubmissionCheckAttempt.objects.create(submission=sub, number=1, result=result)
        self.client.force_login(self.teacher)

    def test_task_window(self):
        url = reverse('worksheet_task_window', args=[self.worksheet.pk, self.items[0].pk])
        response = self.client.get(url)
        self.assertContains(response, 'Найдите отрезок 1')
        self.assertContains(response, 'Маска ответа: так видит ученик')
        self.assertContains(response, 'data-mask-check')
        self.assertContains(response, '<span class="tw-label">Ответ</span>')
        self.assertEqual((response.context['ok'], response.context['answered']), (1, 2))
        self.assertEqual([a['name'] for a in response.context['answers']], ['Петя Белова', 'Петя Жуков'])
        self.assertContains(response, reverse('task_attempts', args=[self.oleg.pk, self.tasks[0].pk]))
        self.assertContains(response, 'Задача 2 →')
        self.assertNotContains(response, '·')
        # чужой пункт листка — 404
        other = WorksheetItem.objects.create(worksheet=make_worksheet(self.teacher), task=self.tasks[1], order=1)
        self.assertEqual(self.client.get(reverse('worksheet_task_window', args=[self.worksheet.pk, other.pk])).status_code, 404)
        # номер в карте ответов открывает это окно
        progress = self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk]))
        self.assertContains(progress, f'data-attempt-url="{url}"')

    def test_student_window(self):
        ActivityEvent.objects.create(
            assignment=self.oleg, event_id=uuid.uuid4(), page_id=uuid.uuid4(), sequence=1, kind='copy',
            text='Найдите отрезок MB', statements=[{'label': '1', 'share': 100}], client_at=timezone.now(), elapsed_ms=1000)
        Review.objects.create(submission=Submission.objects.get(assignment=self.oleg, task=self.tasks[0]), grade='-+')
        response = self.client.get(reverse('task_attempts', args=[self.oleg.pk, self.tasks[0].pk]), {'item': self.items[0].pk})
        self.assertContains(response, 'Задача 1 из 2')
        self.assertContains(response, 'class="live-copy"')
        self.assertContains(response, 'скопировал условие задачи 1 целиком')
        self.assertContains(response, '← Петя Белова')
        self.assertContains(response, 'Задача 2 →')
        self.assertContains(response, '–+ существенное продвижение, 0%')
        self.assertContains(response, '<span class="tw-label">Ответ</span>')
        self.assertNotContains(response, '·')
        # у первого по фамилии нет «предыдущего» ученика и задачи
        first = self.client.get(reverse('task_attempts', args=[self.anna.pk, self.tasks[0].pk]), {'item': self.items[0].pk})
        self.assertNotIn('prev_student', first.context)
        self.assertNotIn('prev_task', first.context)
        self.assertContains(first, 'Не копировал условие.')

    def test_comment_keeps_grade(self):
        url = reverse('grade_task', args=[self.oleg.pk, self.tasks[0].pk])
        self.assertEqual(self.client.post(url, {'grade': '+-'}).json()['caption'], '± незначительная ошибка, 75%')
        result = self.client.post(url, {'comment': ' Проверь вычисления '}).json()
        self.assertEqual((result['grade'], result['feedback']), ('+-', 'Проверь вычисления'))
        review = Review.objects.get(submission__assignment=self.oleg)
        self.assertEqual((review.grade, review.comment), ('+-', 'Проверь вычисления'))
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        self.assertEqual(self.client.post(url, {'grade': 'excellent', 'comment': 'x'}).status_code, 400)
