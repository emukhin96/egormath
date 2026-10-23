"""Панель «Настройки выдачи» самостоятельной по макету E_Settings."""
from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from problems.tests import make_student, make_teacher
from problems.models import Task
from .models import Work, Position, Candidate, Run
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class RunSettingsDrawerTests(TestCase):
    """Панель «Настройки выдачи» (макет E_Settings) на прогрессе самостоятельной
    и смена срока «Закончить не позже» через services.set_deadline."""

    def setUp(self):
        self.teacher = make_teacher('settings_teacher')
        self.students = [make_student(self.teacher, username=f'settings_student{n}') for n in (1, 2)]
        work = Work.objects.create(owner=self.teacher, title='Контрольная: подобие')
        Candidate.objects.create(position=Position.objects.create(work=work),
                                 task=Task.objects.create(text_latex='Сколько будет 2+2?', answer_mask='{{number: 4}}'))
        self.run = svc.prepare(work, self.teacher, [s.pk for s in self.students])
        svc.issue(self.run.pk, True)
        self.started = svc.start(self.run.attempts.get(student=self.students[0]).pk)
        self.client.force_login(self.teacher)

    def test_drawer(self):
        response = self.client.get(reverse('independentworks:progress', args=[self.run.pk]))
        self.assertContains(response, 'data-dialog-open="run-settings"')
        self.assertContains(response, 'Решают 1, сдали 0, не начали 1')
        self.assertContains(response, 'Вариант не начавшим')
        self.assertContains(response, 'name="deadline"')
        self.assertContains(response, 'Закончить не позже')  # Run.deadline — общее окончание
        self.assertNotContains(response, '·')

    def test_drawer_on_add_students_error(self):
        """Ошибка «Выдать ещё» открывает ту же панель целиком: сводка,
        не начавшие и флажки показа (ревью #289)."""
        response = self.client.post(reverse('independentworks:add_students', args=[self.run.pk]), {})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'data-open-on-load', status_code=400)
        self.assertContains(response, 'Решают 1, сдали 0, не начали 1', status_code=400)
        self.assertContains(response, 'Вариант не начавшим', status_code=400)
        self.assertContains(response, 'name="flags" value="answer"', status_code=400)

    def test_deadline(self):
        url = reverse('independentworks:run_deadline', args=[self.run.pk])
        soon = timezone.localtime(self.started.started_at + timedelta(minutes=10)).replace(second=0, microsecond=0)
        self.client.post(url, {'deadline': soon.strftime('%Y-%m-%dT%H:%M')})
        self.run.refresh_from_db()
        self.started.refresh_from_db()
        self.assertEqual(self.run.deadline, soon)
        self.assertEqual(self.started.ends_at, soon)  # срок начатой попытки сокращён до общего
        self.client.post(url, {'deadline': ''})
        self.run.refresh_from_db()
        self.assertIsNone(self.run.deadline)
        response = self.client.post(url, {'deadline': 'завтра'}, follow=True)
        self.assertContains(response, 'Не удалось разобрать срок')

    def test_past_deadline_rejected(self):
        """Срок в прошлом не принимается: иначе начатые попытки необратимо
        закрылись бы (ревью #289)."""
        url = reverse('independentworks:run_deadline', args=[self.run.pk])
        past = timezone.localtime(timezone.now() - timedelta(hours=1)).replace(second=0, microsecond=0)
        response = self.client.post(url, {'deadline': past.strftime('%Y-%m-%dT%H:%M')}, follow=True)
        self.assertContains(response, 'Срок уже прошёл')
        self.run.refresh_from_db()
        self.started.refresh_from_db()
        self.assertIsNone(self.run.deadline)
        self.assertFalse(self.started.finished)
