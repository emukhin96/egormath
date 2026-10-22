"""Карта ответов «в моменте» (макет D_Live): сводка класса, колонка «Сейчас»,
метка «•» за копирование больше одного слова, строка «Верно / решают», порядок."""
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
from .models import Assignment, Submission, SubmissionCheckAttempt


class LiveMapTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.filter(worksheet=self.worksheet).delete()
        self.tasks = [Task.objects.create(text_latex=f'Задача {n}', answer_mask='{{number: 8}}') for n in (1, 2)]
        for order, task in enumerate(self.tasks, 1):
            WorksheetItem.objects.create(worksheet=self.worksheet, task=task, order=order)
        self.people = {}
        for username, last in [('anna', 'Белова'), ('ilya', 'Громов'), ('oleg', 'Жуков')]:
            student = make_student(self.teacher, username=username)
            student.last_name = last
            student.save()
            self.people[username] = Assignment.objects.create(worksheet=self.worksheet, student=student, assigned_by=self.teacher)
        self.url = reverse('worksheet_progress', args=[self.worksheet.pk])
        self.client.force_login(self.teacher)

    def answer(self, assignment, task, result):
        sub = Submission.objects.create(assignment=assignment, task=task, answer_json={'s1': '8'})
        SubmissionCheckAttempt.objects.create(submission=sub, number=1, result=result)
        return sub

    def copy(self, assignment, text):
        return ActivityEvent.objects.create(
            assignment=assignment, event_id=uuid.uuid4(), page_id=uuid.uuid4(), sequence=1, kind='copy',
            text=text, statements=[{'label': '1', 'share': 40}], client_at=timezone.now(), elapsed_ms=1000)

    def test_summary_now_column_and_stats(self):
        anna, ilya = self.people['anna'], self.people['ilya']
        self.answer(anna, self.tasks[0], 'ok')
        self.answer(anna, self.tasks[1], 'wrong')
        anna.status, anna.submitted_at = Assignment.STATUS_SUBMITTED, timezone.now()
        anna.save()
        self.answer(ilya, self.tasks[0], 'ok')
        response = self.client.get(self.url)
        self.assertEqual(response.context['summary'], {'submitted': 1, 'live': 1, 'unopened': 1, 'pending': 1, 'copied': 0})
        now = {p['assignment'].student.username: (p['now_kind'], p['now']) for p in response.context['people']}
        self.assertEqual(now['ilya'][0], 'live')
        self.assertTrue(now['ilya'][1].startswith('на №1, '))
        self.assertEqual(now['oleg'], ('never', 'не открыто'))
        self.assertEqual(now['anna'][0], 'done')
        # №1: верно у обоих ответивших, решает сейчас Илья; №2: 0 из 1
        self.assertEqual([(s['ok'], s['answered'], s['live'], s['tone']) for s in response.context['column_stats']],
                         [(2, 2, 1, 'good'), (0, 1, 0, 'low')])
        self.assertContains(response, 'Класс сейчас')
        self.assertContains(response, 'progress-cell is-live')
        self.assertContains(response, 'Проверить 1')
        self.assertContains(response, 'сейчас 1')
        fragment = self.client.get(self.url, {'fragment': '1'})
        self.assertNotContains(fragment, '·')
        self.assertNotContains(fragment, 'fragment=1')

    def test_old_answer_is_not_live(self):
        sub = self.answer(self.people['ilya'], self.tasks[0], 'ok')
        Submission.objects.filter(pk=sub.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        sub.parts.update(updated_at=timezone.now() - timedelta(hours=2))
        response = self.client.get(self.url)
        ilya = next(p for p in response.context['people'] if p['assignment'] == self.people['ilya'])
        self.assertEqual(ilya['now_kind'], 'idle')
        self.assertEqual(response.context['summary']['live'], 0)

    def test_copy_mark_needs_more_than_one_word(self):
        url = self.url
        first = self.client.get(url, {'fragment': '1'})
        self.copy(self.people['oleg'], 'отрезки')
        self.assertNotContains(self.client.get(url), 'class="live-copy" title')
        self.copy(self.people['oleg'], 'Найдите отрезок $MB$')
        response = self.client.get(url)
        self.assertEqual(response.context['summary']['copied'], 1)
        self.assertContains(response, 'class="live-copy" title="Скопировал часть условия задачи 1 (40%)"')
        # событие копирования меняет ETag фрагмента — метка появится при опросе
        self.assertEqual(self.client.get(url, {'fragment': '1'}, HTTP_IF_NONE_MATCH=first['ETag']).status_code, 200)

    def test_order(self):
        self.answer(self.people['oleg'], self.tasks[0], 'ok')
        self.answer(self.people['oleg'], self.tasks[1], 'ok')
        self.answer(self.people['anna'], self.tasks[0], 'ok')
        names = lambda order: [p['assignment'].student.username for p in self.client.get(self.url, {'order': order}).context['people']]
        self.assertEqual(names('name'), ['anna', 'ilya', 'oleg'])
        self.assertEqual(names('behind'), ['ilya', 'anna', 'oleg'])
        self.assertEqual(names('result'), ['oleg', 'anna', 'ilya'])
        self.assertEqual(names('nonsense'), ['anna', 'ilya', 'oleg'])
