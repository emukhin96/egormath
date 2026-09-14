"""Общий каталог и изменение явно выбранных подпунктов."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from problems.models import Task, TaskSubitem
from .models import Work, Position, Candidate


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class BuilderTests(TestCase):
    def test_catalog_filter_and_edit_selected_parts(self):
        teacher = get_user_model().objects.create_superuser('builder_teacher', password='test')
        self.client.force_login(teacher)
        work = Work.objects.create(owner=teacher, title='Подпункты')
        position = Position.objects.create(work=work)
        task = Task.objects.create(text_latex='Условие', grade_level=9)
        a = TaskSubitem.objects.create(task=task, text_latex='Первый', order=1)
        b = TaskSubitem.objects.create(task=task, text_latex='Второй', order=2)
        candidate = Candidate.objects.create(position=position, task=task)
        url = reverse('independentworks:pick', args=[position.pk])
        response = self.client.get(url, {'grade': '9', 'q': str(task.pk)})
        self.assertContains(response, 'task-filters')
        self.assertContains(response, '<option value="9" selected>')
        self.assertContains(response, 'Утверждённый пул')
        self.assertEqual(list(response.context['page']), [task])
        self.assertEqual(self.client.post(url, {'task': task.pk, 'candidate': candidate.pk, 'parts_mode': 'selected', 'parts': [b.pk]}).status_code, 302)
        candidate.refresh_from_db()
        self.assertEqual(candidate.subitem_ids, [b.pk])
        self.assertEqual(self.client.post(url, {'task': task.pk, 'candidate': candidate.pk, 'parts_mode': 'selected'}).status_code, 400)
        candidate.refresh_from_db()
        self.assertEqual(candidate.subitem_ids, [b.pk])
        self.assertEqual(self.client.get(reverse('independentworks:edit', args=[work.pk])).status_code, 200)
