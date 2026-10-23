"""Работа ученика в самостоятельной глазами учителя (макет D_Timeline)."""
from django.test import TestCase, override_settings
from django.urls import reverse
from assignments.checks import parse_mask
from problems.tests import make_student, make_teacher
from problems.models import Task
from .models import Work, Position, Candidate
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class AttemptPageTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('attempt_teacher')
        self.student = make_student(self.teacher, username='attempt_student')
        work = Work.objects.create(owner=self.teacher, title='Контрольная: подобие')
        Candidate.objects.create(position=Position.objects.create(work=work, order=1),
                                 task=Task.objects.create(text_latex='Сколько будет 2+2?', answer_mask='{{number: 4}}'))
        Candidate.objects.create(position=Position.objects.create(work=work, order=2),
                                 task=Task.objects.create(text_latex='Решите неравенство x>1', answer_latex='$(1; +\\infty)$',
                                                          answer_mask='$x\\in${{range: (1; +\\infty)}}'))
        self.run = svc.prepare(work, self.teacher, [self.student.pk])
        svc.issue(self.run.pk, True)
        self.attempt = svc.start(self.run.attempts.get().pk)
        self.point = self.attempt.variant.points.order_by('position').first()
        svc.save_answer(self.attempt.pk, self.point.pk, 0, {parse_mask(self.point.snapshot['mask']).slots[0].name: '4'})
        self.client.force_login(self.teacher)
        self.url = reverse('independentworks:attempt', args=[self.attempt.pk])

    def test_timeline_layout(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'class="tl-head"')
        self.assertContains(response, f'<h1>{self.student.get_full_name()}')
        self.assertContains(response, 'вариант 1, 40 мин; начал')
        self.assertContains(response, 'решает, до')
        self.assertContains(response, 'Начал работу')
        self.assertContains(response, 'class="tl-row', count=3)  # заголовок и два задания
        self.assertContains(response, reverse('independentworks:point_detail', args=[self.attempt.pk, self.point.pk]))
        self.assertNotContains(response, 'Работа над ошибками')  # только после сдачи
        self.assertNotContains(response, '·')

    def test_after_submit(self):
        svc.submit(self.attempt.pk)
        response = self.client.get(self.url)
        self.assertContains(response, 'Сдал работу')
        self.assertContains(response, 'Работа над ошибками')
        self.assertContains(response, 'progress-mark progress-ok')
        self.assertContains(response, '1 из 2, 50%')
        # Оценка учителя — символом в колонке «Оценка» (ревью #294)
        self.client.post(reverse('independentworks:review', args=[self.attempt.pk, self.point.pk]), {'grade': '+-'})
        graded = self.client.get(self.url)
        self.assertContains(graded, 'tl-grade tl-grade-good')
        self.assertContains(graded, '>±</button>')

    def test_range_reference_as_text(self):
        """Эталон промежутка — текстом ответа, а не LaTeX в поле маски."""
        response = self.client.get(self.url)
        self.assertNotContains(response, 'mask-slot-range')
        self.assertContains(response, '+\\infty')

    def test_student_keeps_own_page(self):
        self.client.force_login(self.student)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'class="tl-head"')
        self.assertContains(response, 'data-iw-focus')
