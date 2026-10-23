"""Окно «задание у ученика» на прогрессе самостоятельной (макет D_AnswerView)."""
import uuid
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from assignments.checks import parse_mask
from problems.tests import make_student, make_teacher
from problems.models import Task
from workaudit.models import ActivityEvent
from .models import Work, Position, Candidate
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class PointWindowTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('window_teacher')
        self.students = [make_student(self.teacher, username=f'window_student{n}') for n in (1, 2)]
        work = Work.objects.create(owner=self.teacher, title='Контрольная: подобие')
        for n in (1, 2):
            Candidate.objects.create(position=Position.objects.create(work=work, order=n),
                                     task=Task.objects.create(text_latex=f'Сколько будет {n}+{n}?', answer_mask=f'{{{{number: {2 * n}}}}}'))
        self.run = svc.prepare(work, self.teacher, [s.pk for s in self.students])
        svc.issue(self.run.pk, True)
        self.attempt = svc.start(self.run.attempts.get(student=self.students[0]).pk)
        self.point = self.attempt.variant.points.order_by('position').first()
        slot = parse_mask(self.point.snapshot['mask']).slots[0].name
        svc.save_answer(self.attempt.pk, self.point.pk, 0, {slot: '2'})
        self.client.force_login(self.teacher)

    def url(self, attempt, point):
        return reverse('independentworks:point_detail', args=[attempt.pk, point.pk])

    def test_window_before_submit(self):
        response = self.client.get(self.url(self.attempt, self.point))
        self.assertContains(response, 'class="tw"')
        self.assertContains(response, 'Задание 1 из 2, вариант')
        self.assertContains(response, f'id="progress-dialog-title">{self.students[0].get_full_name()}')
        self.assertContains(response, 'Работа ещё не сдана')
        self.assertContains(response, 'Оценить и прокомментировать можно после сдачи работы.')
        self.assertNotContains(response, 'data-grade-url')
        self.assertContains(response, 'Задание 2 →')
        self.assertNotContains(response, '·')

    def test_window_after_submit_grades_and_neighbours(self):
        svc.submit(self.attempt.pk)
        other = self.run.attempts.exclude(pk=self.attempt.pk).get()
        response = self.client.get(self.url(self.attempt, self.point))
        self.assertContains(response, 'автосверка <b class="tw-verdict">✓')
        self.assertContains(response, 'data-grade-url')
        self.assertContains(response, f'name="p{self.point.pk}_comment"')
        # Соседний ученик — тот же номер в своём варианте
        same = other.variant.points.get(position=self.point.position, part=self.point.part)
        self.assertContains(response, self.url(other, same))
        graded = self.client.post(reverse('independentworks:review', args=[self.attempt.pk, self.point.pk]),
                                  {'grade': '+'}, HTTP_ACCEPT='application/json').json()
        self.assertEqual(graded['caption'], '+ полностью правильно, 100%')
        self.assertContains(self.client.get(self.url(self.attempt, self.point)), 'оценка <b class="tw-verdict">+')

    def test_copies_in_this_task(self):
        ActivityEvent.objects.create(attempt=self.attempt, event_id=uuid.uuid4(), page_id=uuid.uuid4(), sequence=1,
                                     kind='copy', text='Сколько будет 1+1', client_at=timezone.now(), elapsed_ms=0,
                                     statements=[{'label': self.point.label, 'share': 100}], whole=True)
        response = self.client.get(self.url(self.attempt, self.point))
        self.assertContains(response, '«Сколько будет 1+1»')
        self.assertContains(response, 'Копировал текст условия этого задания')
