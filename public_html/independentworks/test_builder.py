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

    def test_same_issuance_form_and_worksheet_entrypoint(self):
        teacher = get_user_model().objects.create_superuser('issuer_teacher', password='test')
        self.client.force_login(teacher)
        work = Work.objects.create(owner=teacher, title='Общая выдача')
        response = self.client.get(reverse('assignment_create'), {'mode': 'independent', 'work': work.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'assignments/assignment_create.html')
        self.assertTemplateUsed(response, 'assignments/_recipients.html')
        self.assertContains(response, 'student-filter')
        self.assertContains(response, 'id_duration')
        self.assertNotContains(response, 'id_check_visibility')
        ordinary = self.client.get(reverse('assignment_create'))
        self.assertContains(ordinary, 'id_check_visibility')
        self.assertNotContains(ordinary, 'id_duration')
        with override_settings(INDEPENDENT_WORKS_ENABLED=False):
            self.assertEqual(self.client.get(reverse('assignment_create'), {'mode': 'independent'}).status_code, 404)

    def test_recommendations_survive_catalog_filters(self):
        from .models import Family
        teacher = get_user_model().objects.create_superuser('recommend_teacher')
        self.client.force_login(teacher)
        work = Work.objects.create(owner=teacher, title='Рекомендации')
        position = Position.objects.create(work=work)
        base = Task.objects.create(text_latex='Исходная', grade_level=9)
        analog = Task.objects.create(text_latex='Связанный аналог', grade_level=8)
        Candidate.objects.create(position=position, task=base)
        family = Family.objects.create(key='manual:recommend', title='Пара')
        family.tasks.add(base, analog)
        response = self.client.get(reverse('independentworks:pick', args=[position.pk]), {'q': str(base.pk), 'grade': '9'})
        self.assertEqual(list(response.context['page']), [base])
        self.assertEqual(list(response.context['recommended']), [analog])

    def test_workspace_selection_and_add_preserve_preparation(self):
        teacher = get_user_model().objects.create_superuser('workspace_teacher')
        self.client.force_login(teacher)
        work = Work.objects.create(owner=teacher, title='Рабочее место')
        first = Position.objects.create(work=work, order=1)
        second = Position.objects.create(work=work, order=2)
        task = Task.objects.create(text_latex='Условие', answer_mask='{{number: 1}}')
        Candidate.objects.create(position=second, task=task)
        url = reverse('independentworks:edit', args=[work.pk])
        response = self.client.get(url, {'position': second.pk, 'resume': '17'})
        self.assertEqual(response.context['selected_position'], second)
        self.assertContains(response, f'position={first.pk}&amp;resume=17')
        response = self.client.post(url + '?resume=17', {'action': 'add'})
        new = work.positions.last()
        self.assertIn(f'position={new.pk}', response.url)
        self.assertIn('resume=17', response.url)
        response = self.client.get(reverse('independentworks:pick', args=[second.pk]), {'q': str(task.pk)})
        self.assertEqual(response.context['picker_tab'], 'catalog')
        self.assertContains(response, f'?position={second.pk}')

    def test_source_mode_prevents_hidden_source_priority(self):
        from worksheets.models import Worksheet, WorksheetItem
        teacher = get_user_model().objects.create_superuser('source_teacher')
        self.client.force_login(teacher)
        sheet = Worksheet.objects.create(owner=teacher, title='Источник')
        WorksheetItem.objects.create(worksheet=sheet, task=Task.objects.create(text_latex='Задача'))
        url = reverse('independentworks:create')
        response = self.client.post(url, {'title': 'Пустой', 'source_mode': 'blank', 'worksheet': sheet.pk, 'collection': 99999})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Work.objects.get(title='Пустой').positions.exists())
        response = self.client.post(url, {'title': 'Копия', 'source_mode': 'sheet', 'worksheet': sheet.pk, 'collection': 99999})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Work.objects.get(title='Копия').positions.count(), 1)
        self.assertEqual(self.client.post(url, {'title': 'Без источника', 'source_mode': 'sheet'}).status_code, 400)

    def test_material_picker_search_and_pagination(self):
        teacher = get_user_model().objects.create_superuser('material_teacher')
        self.client.force_login(teacher)
        for n in range(31):
            work = Work.objects.create(owner=teacher, title=f'Материал {n:02}')
            Position.objects.create(work=work, text='Пояснение')
            Position.objects.create(work=work)
        url = reverse('assignment_create')
        page = self.client.get(url, {'mode': 'independent', 'page': 2}).context['work_options']
        self.assertEqual(len(page.object_list), 1)
        self.assertEqual(page.object_list[0].number_count, 1)
        page = self.client.get(url, {'mode': 'independent', 'q': 'Материал 12'}).context['work_options']
        self.assertEqual([w.title for w in page], ['Материал 12'])
