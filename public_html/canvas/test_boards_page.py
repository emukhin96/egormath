"""Доски учеников по макету E_Boards: порядок карточек, отметка по задаче,
точка копирования."""
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment, Submission
from problems.models import Task
from problems.tests import make_student, make_teacher
from workaudit.models import ActivityEvent
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet


class BoardsPageTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher, n_tasks=0)
        self.task = Task.objects.create(text_latex='Найдите корень уравнения $2x=8$', answer_mask='{{number: 4}}')
        WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=1)
        self.anna = make_student(self.teacher, username='anna')
        self.oleg = make_student(self.teacher, username='oleg')
        for user, last in ((self.anna, 'Белова'), (self.oleg, 'Жуков')):
            user.last_name = last
            user.save(update_fields=['last_name'])
        self.a_anna, self.a_oleg = (Assignment.objects.create(worksheet=self.worksheet, student=s, assigned_by=self.teacher)
                                    for s in (self.anna, self.oleg))
        Submission.objects.create(assignment=self.a_anna, task=self.task, answer_json={'s1': '4'}, auto_check='ok')
        Submission.objects.create(assignment=self.a_oleg, task=self.task, answer_json={'s1': '5'}, auto_check='wrong')
        self.client.force_login(self.teacher)

    def page(self, **params):
        return self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk]), params)

    def live(self, **params):
        return self.client.get(reverse('worksheet_boards_live', args=[self.worksheet.pk]), params).json()

    def test_order_and_marks(self):
        names = [s['student'] for s in self.live(task=self.task.pk, order='name')['states']]
        self.assertEqual(names, [self.anna.get_full_name(), self.oleg.get_full_name()])
        states = self.live(task=self.task.pk, order='wrong')['states']
        self.assertEqual(states[0]['assignment'], self.a_oleg.pk)
        self.assertEqual({s['assignment']: s['mark'] for s in states}, {self.a_anna.pk: '✓', self.a_oleg.pk: '×'})
        # без задачи отметки нет, «с неверным ответом» не предлагается
        self.assertEqual({s['mark'] for s in self.live()['states']}, {''})
        self.assertNotContains(self.page(), 'Сначала с неверным ответом')
        page = self.page(task=self.task.pk, order='wrong')
        self.assertContains(page, '<option value="wrong" selected>')
        self.assertContains(page, 'order=wrong')  # живой опрос с тем же порядком
        self.assertContains(page, 'data-mark="×"')

    def test_copy_dot(self):
        ActivityEvent.objects.create(assignment=self.a_oleg, event_id=uuid.uuid4(), page_id=uuid.uuid4(), sequence=1,
                                     kind='copy', text='Найдите корень уравнения', client_at=timezone.now(), elapsed_ms=0,
                                     statements=[{'label': '1', 'share': 100}], whole=True)
        self.assertContains(self.page(task=self.task.pk), 'title="Копировал текст условия"', count=1)
        self.assertContains(self.page(), 'title="Копировал текст условия"', count=1)
