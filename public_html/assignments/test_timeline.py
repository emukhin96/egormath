"""Хронология работы ученика (макет D_Timeline, assignments/timeline.py):
лента событий, дорожка, таблица ответов с оценкой, действия и входы."""
import uuid
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from problems.models import Task
from problems.tests import make_student, make_teacher
from workaudit.models import ActivityEvent
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .models import Assignment, Review, Submission, SubmissionCheckAttempt


class TimelineTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.filter(worksheet=self.worksheet).delete()
        self.tasks = [Task.objects.create(text_latex=f'Найдите площадь фигуры {n}', answer_mask='S = {{number: 30}}') for n in (1, 2)]
        self.items = [WorksheetItem.objects.create(worksheet=self.worksheet, task=t, order=n) for n, t in enumerate(self.tasks, 1)]
        student = make_student(self.teacher, username='oleg')
        self.assignment = Assignment.objects.create(worksheet=self.worksheet, student=student, assigned_by=self.teacher)
        sub = Submission.objects.create(assignment=self.assignment, task=self.tasks[0], answer_json={'s1': '30'})
        for number, (value, result) in enumerate([('23', 'wrong'), ('30', 'ok')], 1):
            SubmissionCheckAttempt.objects.create(submission=sub, number=number, result=result, snapshot={
                'targets': [{'kind': 'task', 'id': self.tasks[0].pk, 'answer': f'S = {value}', 'result': result}]})
        start = timezone.now() - timedelta(minutes=30)
        page = uuid.uuid4()
        for sequence, (kind, offset, extra) in enumerate([
                ('copy', 60, {'text': 'Найдите площадь фигуры', 'statements': [{'label': '1', 'share': 100}], 'whole': True}),
                ('hidden', 120, {}), ('visible', 240, {})]):
            ActivityEvent.objects.create(assignment=self.assignment, event_id=uuid.uuid4(), page_id=page, sequence=sequence,
                                         kind=kind, client_at=start + timedelta(seconds=offset), elapsed_ms=offset * 1000, **extra)
        self.assignment.status = Assignment.STATUS_SUBMITTED
        self.assignment.submitted_at = timezone.now()
        self.assignment.save()
        self.url = reverse('assignment_timeline', args=[self.assignment.pk])
        self.client.force_login(self.teacher)

    def test_page(self):
        response = self.client.get(self.url)
        texts = [e['text'] for e in response.context['events']]
        self.assertEqual(texts[0], 'Начал работу')
        self.assertEqual(texts[-1], 'Сдал работу')
        self.assertIn('Скопировал условие задачи 1 целиком', texts)
        self.assertIn('Ушёл со страницы', texts)
        self.assertIn('Задача 1: S = 23', texts)
        away = next(e for e in response.context['events'] if e['kind'] == 'away')
        self.assertEqual(away['detail'], 'вернулся через 2 мин')
        self.assertEqual({s['kind'] for s in response.context['track']['segments']}, {'away', 'clipboard', 'wrong'})
        rows = response.context['rows']
        self.assertEqual([(r['number'], r['answered'], r['pending'], r['copied']) for r in rows],
                         [(1, True, True, True), (2, False, False, False)])
        self.assertContains(response, 'без оценки: 1')
        self.assertContains(response, 'class="live-copy"')
        self.assertContains(response, 'Завершить проверку')
        self.assertNotContains(response, '·')

    def test_grade_and_actions(self):
        Review.objects.create(submission=Submission.objects.get(assignment=self.assignment), grade='+-')
        response = self.client.get(self.url)
        self.assertEqual(response.context['rows'][0]['grade_tone'], 'good')
        self.assertEqual(response.context['pending'], [])
        self.client.post(reverse('save_review', args=[self.assignment.pk]), {'action': 'complete'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_REVIEWED)
        self.assertEqual(Review.objects.get().grade, '+-')

    def test_entry_points_and_access(self):
        self.assertContains(self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk])), self.url)
        window = self.client.get(reverse('task_attempts', args=[self.assignment.pk, self.tasks[0].pk]), {'item': self.items[0].pk})
        self.assertContains(window, self.url)
        self.client.force_login(make_teacher('stranger'))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_review_fixes(self):
        """Ревью #282: старая отметка «Выполнено» (done без grade) — оценка,
        у повторённой задачи разные префиксы полей, возврат с подтверждением."""
        Review.objects.create(submission=Submission.objects.get(assignment=self.assignment), grade='', done=True)
        WorksheetItem.objects.create(worksheet=self.worksheet, task=self.tasks[0], order=3)
        response = self.client.get(self.url)
        rows = response.context['rows']
        self.assertEqual([(r['graded'], r['pending'], r['grade_tone']) for r in rows if r['task'] == self.tasks[0]],
                         [(True, False, 'good'), (True, False, 'good')])
        self.assertEqual(response.context['pending'], [])
        names = [frag['name'] for r in rows for c in r['cells'] if c['shown'] for frag in c['shown'] if 'name' in frag]
        self.assertEqual(len(names), 2)
        self.assertEqual(len(names), len(set(names)))
        self.assertContains(response, "confirm('Вернуть работу ученику на доработку?')")

    def test_returned_work_and_repeated_task(self):
        """Ревью #282: после возврата дорожка тянется до последнего события, в
        шапке «сдавал …, возвращена на доработку»; у задачи, стоящей в листке
        дважды, события подписаны обоими номерами."""
        self.assignment.status = Assignment.STATUS_RETURNED
        self.assignment.submitted_at = timezone.now() - timedelta(minutes=20)
        self.assignment.save()
        sub = Submission.objects.get(assignment=self.assignment)
        later = SubmissionCheckAttempt.objects.create(submission=sub, number=3, result='ok', snapshot={
            'targets': [{'kind': 'task', 'id': self.tasks[0].pk, 'answer': 'S = 30', 'result': 'ok'}]})
        WorksheetItem.objects.create(worksheet=self.worksheet, task=self.tasks[0], order=3)
        response = self.client.get(self.url)
        self.assertEqual(response.context['track']['end'], later.created_at)
        self.assertContains(response, 'возвращена на доработку')
        self.assertIn('Задача 1, 3: S = 30', [e['text'] for e in response.context['events']])

    def test_device_clock_skew(self):
        """Ревью #282: часы устройства на час вперёд — копирование всё равно
        встаёт до сдачи, по времени сервера (received_at)."""
        ActivityEvent.objects.filter(assignment=self.assignment).delete()
        submitted = timezone.now() + timedelta(minutes=5)
        Assignment.objects.filter(pk=self.assignment.pk).update(submitted_at=submitted)
        ActivityEvent.objects.create(assignment=self.assignment, event_id=uuid.uuid4(), page_id=uuid.uuid4(), sequence=1,
                                     kind='copy', text='Найдите площадь фигуры', statements=[{'label': '1', 'share': 100}],
                                     client_at=timezone.now() + timedelta(hours=1), elapsed_ms=1000)
        kinds = [e['kind'] for e in self.client.get(self.url).context['events']]
        self.assertLess(kinds.index('clipboard'), kinds.index('submit'))
