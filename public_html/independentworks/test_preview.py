"""«Перед выдачей» самостоятельной по макету E_Preview."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from problems.tests import make_student, make_teacher
from problems.models import Task
from .models import Work, Position, Candidate
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class PreviewScreenTests(TestCase):
    """«Перед выдачей» по макету E_Preview: шапка с «Выдать N», распределение
    радиокнопками сохраняется тем же POST, без «·»."""

    def setUp(self):
        self.teacher = make_teacher('preview_teacher')
        self.students = [make_student(self.teacher, username=f'preview_student{n}') for n in (1, 2)]
        self.work = Work.objects.create(owner=self.teacher, title='Контрольная: подобие')
        position = Position.objects.create(work=self.work)
        for n in (1, 2):
            Candidate.objects.create(position=position, task=Task.objects.create(text_latex=f'Сколько будет {n}+{n}?', answer_mask=f'{{{{number: {2 * n}}}}}'))
        self.run = svc.prepare(self.work, self.teacher, [s.pk for s in self.students])
        self.client.force_login(self.teacher)
        self.url = reverse('independentworks:preview', args=[self.run.pk])

    def test_screen_and_distribution(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Перед выдачей: Контрольная: подобие')
        self.assertContains(response, 'Выдать 2</button>')
        self.assertContains(response, 'data-variant-count="1"')
        self.assertContains(response, f'name="student_{self.students[0].pk}" value="1"')
        # Номер с подпунктами — одна группа pv-group, как карточка у ученика (ревью #286)
        self.assertContains(response, 'class="pv-group"', count=len(self.run.plan['variants']))
        # Сохранения распределения — очередью, «Выдать» ждёт её (ревью #286)
        self.assertContains(response, 'EgorAutosave.enqueue(form, operation)')
        self.assertContains(response, 'if (pending) event.preventDefault()')
        self.assertNotContains(response, '·')
        variants = len(self.run.plan['variants'])
        data = {f'student_{s.pk}': str(variants) for s in self.students}
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.run.refresh_from_db()
        self.assertEqual(set(self.run.plan['students'].values()), {variants})
        # fetch получает JSON, а не редирект; после выдачи — ошибка, не «успех» (ревью #286)
        ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        self.assertEqual(self.client.post(self.url, data, **ajax).json(), {'ok': True})
        self.run.issued_at = timezone.now()
        self.run.save(update_fields=['issued_at'])
        late = self.client.post(self.url, data, **ajax)
        self.assertEqual(late.status_code, 409)
        self.assertIn('уже выдана', late.json()['message'])
