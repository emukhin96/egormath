"""Кабинет учителя по макету E_Home: идёт сейчас, ждут проверки, сроки на
неделе, сигналы о копировании (accounts/teacher_home.py)."""
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from accounts.teacher_home import running_works, week_deadlines
from assignments.models import Assignment
from independentworks import services as svc
from independentworks.models import Candidate, Position, Work
from problems.models import Task
from workaudit.models import ActivityEvent
from workaudit.services import copied_words, copy_marks
from worksheets.models import Worksheet


def copy_event(text, assignment=None, attempt=None):
    return ActivityEvent.objects.create(
        assignment=assignment, attempt=attempt, event_id=uuid.uuid4(), page_id=uuid.uuid4(),
        sequence=1, kind='copy', text=text, statements=[{'label': '1', 'share': 40}],
        client_at=timezone.now(), elapsed_ms=1000)


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class TeacherHomeTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('teacher', first_name='Егор', last_name='Мухин')
        Profile.objects.create(user=self.teacher, role=Profile.ROLE_TEACHER)
        self.anna = User.objects.create_user('anna', first_name='Анна', last_name='Белова')
        Profile.objects.create(user=self.anna, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        self.oleg = User.objects.create_user('oleg', first_name='Олег', last_name='Жуков')
        Profile.objects.create(user=self.oleg, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        self.sheet = Worksheet.objects.create(owner=self.teacher, title='Пропорциональные отрезки')
        self.submitted = Assignment.objects.create(
            worksheet=self.sheet, student=self.anna, status=Assignment.STATUS_SUBMITTED,
            submitted_at=timezone.now(), due_at=timezone.now() + timedelta(days=1))
        self.open = Assignment.objects.create(
            worksheet=self.sheet, student=self.oleg, due_at=timezone.now() + timedelta(days=1))
        work = Work.objects.create(owner=self.teacher, title='Контрольная: подобие')
        task = Task.objects.create(text_latex='Два плюс два?', answer_mask='{{number: 4}}')
        Candidate.objects.create(position=Position.objects.create(work=work), task=task)
        run = svc.prepare(work, self.teacher, [self.anna.pk, self.oleg.pk])
        svc.issue(run.pk, True)  # один номер на двоих — повтор подтверждаем
        self.attempt = svc.start(run.attempts.get(student=self.anna).pk)
        self.client.force_login(self.teacher)

    def test_sections(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Кабинет учителя')
        # Идёт сейчас: самостоятельная с начатой попыткой и живым таймером
        self.assertContains(response, 'class="now-card"')
        self.assertContains(response, 'Контрольная: подобие')
        self.assertContains(response, 'Решают 1, сдали 0, не начали 1')
        self.assertContains(response, 'data-countdown')
        # Ждут проверки: сданный листок; сроки: сдали 1 из 2
        self.assertEqual([g['title'] for g in response.context['review_groups']], ['Пропорциональные отрезки'])
        self.assertContains(response, 'сдали 1 из 2')
        self.assertNotContains(response, 'sidebar-section')
        self.assertNotContains(response, '·')

    def test_copy_signal_needs_more_than_one_word(self):
        copy_event('отрезки', assignment=self.open)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['signals'], [])
        copy_event('Найдите площадь фигуры', attempt=self.attempt)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual([s['name'] for s in response.context['signals']], ['Анна Белова'])
        self.assertContains(response, 'class="copy-mark"')

    def test_copy_marks_and_words(self):
        one = copy_event('отрезки', assignment=self.open)
        self.assertEqual(copied_words(one), 1)
        formula = copy_event('Найдите $AB^2$', assignment=self.submitted)
        self.assertEqual(copied_words(formula), 2)
        self.assertEqual(copy_marks('assignment', [self.open, self.submitted]), {self.submitted.pk: [formula]})

    def test_running_uses_one_now(self):
        """Попытка истекает между отбором в SQL и разбором (ревью #272):
        активность считается по тому же now, без 500 на пустом max()."""
        from unittest.mock import patch
        self.attempt.refresh_from_db()
        moment = self.attempt.ends_at - timedelta(seconds=1)
        later = self.attempt.ends_at + timedelta(seconds=1)
        with patch('independentworks.models.timezone.now', return_value=later):
            cards = running_works(self.teacher, now=moment)
        self.assertEqual([(c['active'], c['finished']) for c in cards], [(1, 0)])
        self.assertEqual(running_works(self.teacher, now=later), [])

    def test_deadlines_split_by_due_day(self):
        """Один листок, два срока (ревью #272): прошедший срок одной группы
        не делает просроченными учеников с будущим сроком."""
        Assignment.objects.filter(pk=self.submitted.pk).update(due_at=timezone.now() - timedelta(days=1))
        Assignment.objects.filter(pk=self.open.pk).update(due_at=timezone.now() + timedelta(days=5))
        sheet_rows = [r for r in week_deadlines(self.teacher) if r['title'] == self.sheet.title]
        self.assertEqual([(r['passed'], r['total'], r['left']) for r in sheet_rows], [(True, 1, 0), (False, 1, 1)])
