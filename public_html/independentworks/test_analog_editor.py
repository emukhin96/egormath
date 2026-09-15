"""Отмена аналога ничего не создаёт; сохранение переносит все материалы."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from problems.models import Task, TaskSubitem, TaskImage, Source, TaskSource
from .models import Work, Position, Candidate, Family


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class AnalogDraftTests(TestCase):
    def test_unsaved_invalid_and_saved_analog(self):
        teacher = get_user_model().objects.create_superuser('draft_teacher')
        self.client.force_login(teacher)
        work = Work.objects.create(owner=teacher, title='Черновик')
        p = Position.objects.create(work=work)
        source = Task.objects.create(text_latex='Исходная задача', answer_mask='{{number: 2}}')
        part = TaskSubitem.objects.create(task=source, order=1, text_latex='Подпункт', answer_mask='{{number: 3}}')
        TaskImage.objects.create(task=source, image='tasks/existing.png')
        book = Source.objects.create(title='Источник')
        TaskSource.objects.create(task=source, source=book, number='1', source_path=['Глава'], page=10)
        Candidate.objects.create(position=p, task=source)
        start = self.client.post(reverse('independentworks:create_analog', args=[p.pk, source.pk]))
        self.assertEqual(Task.objects.count(), 1)
        self.assertFalse(Family.objects.exists())
        page = self.client.get(start.url)
        self.assertTemplateUsed(page, 'problems/task_form.html')
        self.assertContains(page, 'Назад к подбору')
        self.assertEqual(Task.objects.count(), 1)
        invalid = self.client.post(start.url, {'text_latex':''})
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(Task.objects.count(), 1)
        data = {'text_latex':'Сохранённый аналог', 'columns':1, 'stars':0}
        for name in ('formset', 'subitem_formset', 'image_formset'):
            fs = page.context[name]
            initial = fs.initial_extra or []
            data.update({fs.prefix+'-TOTAL_FORMS':len(initial), fs.prefix+'-INITIAL_FORMS':0})
            for i, row in enumerate(initial):
                for key, value in row.items():
                    data[f'{fs.prefix}-{i}-{key}'] = '' if value is None else value
        saved = self.client.post(start.url, data)
        self.assertEqual(saved.status_code, 302)
        copy = Task.objects.exclude(pk=source.pk).get()
        self.assertEqual(copy.subitems.get().text_latex, part.text_latex)
        self.assertEqual(copy.subitems.get().answer_mask, part.answer_mask)
        self.assertEqual(copy.images.get().image.name, source.images.get().image.name)
        self.assertEqual(copy.source_refs.get().source, book)
        self.assertEqual(copy.source_refs.get().source_path, ['Глава'])
        self.assertEqual(copy.source_refs.get().page, 10)
        self.assertEqual(p.candidates.count(), 2)
        self.assertEqual(set(copy.analog_families.get().tasks.all()), {source, copy})
        self.client.post(start.url, data)
        self.assertEqual(Task.objects.count(), 2)
