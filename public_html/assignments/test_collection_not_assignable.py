"""Подборку нельзя задать ученикам — ни одним путём, даже автору.

Подборка — образец: выдают её копию («Взять как листок»). Уже созданные
выдачи подборки продолжают работать у ученика и учителя.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from independentworks.models import Candidate, Work
from problems.models import Source, Task, TaskSource
from problems.tests import make_student, make_teacher
from worksheets.models import Collection, Worksheet, WorksheetItem

from .forms import AssignmentCreateForm
from .models import Assignment


class CollectionNotAssignableTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.student2 = make_student(self.teacher, 'student2')
        self.admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        self.sheet = Worksheet.objects.create(title='§ 5. Виета', owner=self.teacher)
        self.task = Task.objects.create(
            text_latex='Найдите сумму корней $x^2-7x+10=0$.',
            answer_latex='7', created_by=self.teacher)
        WorksheetItem.objects.create(worksheet=self.sheet, task=self.task, order=10)
        self.collection = Collection.objects.create(
            worksheet=self.sheet, source=Source.objects.create(title='Задачник'),
            locator='p5', is_published=True)
        self.plain = Worksheet.objects.create(title='Домашка', owner=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def assert_refused(self, response):
        self.assertRedirects(
            response, reverse('collection_detail', args=[self.collection.pk]),
            fetch_redirect_response=False)
        self.assertFalse(Assignment.objects.filter(worksheet=self.sheet).exists())

    def test_assignable_excludes_collections(self):
        self.assertTrue(self.sheet.is_collection)
        self.assertFalse(self.plain.is_collection)
        for user in (self.teacher, self.admin):
            ids = set(Worksheet.assignable_to(user).values_list('pk', flat=True))
            self.assertNotIn(self.sheet.pk, ids)
            self.assertIn(self.plain.pk, ids)
        form = AssignmentCreateForm(teacher=self.admin)
        self.assertNotIn(self.sheet, form.fields['worksheet'].queryset)

    def test_assign_worksheet_refused_for_author_and_superuser(self):
        for username in ('teacher1', 'admin'):
            self.client.login(username=username, password='pass12345')
            response = self.client.post(
                reverse('assign_worksheet', args=[self.sheet.pk]),
                {'students': [self.student.pk]})
            self.assert_refused(response)
        response = self.client.get(response.url)
        self.assertContains(response, 'её нельзя задать')

    def test_assignment_create_refused(self):
        for username in ('teacher1', 'admin'):
            self.client.login(username=username, password='pass12345')
            self.assert_refused(self.client.get(
                reverse('assignment_create'), {'worksheet': self.sheet.pk}))
            self.assert_refused(self.client.post(reverse('assignment_create'), {
                'worksheet': self.sheet.pk, 'students': [self.student.pk],
                'check_visibility': Assignment.CHECK_LIVE}))
        # Обычный листок выдаётся как раньше
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('assignment_create'), {
            'worksheet': self.plain.pk, 'students': [self.student.pk],
            'check_visibility': Assignment.CHECK_LIVE})
        self.assertTrue(Assignment.objects.filter(worksheet=self.plain).exists())

    def test_group_update_keeps_old_but_adds_nobody(self):
        old = Assignment.objects.create(
            worksheet=self.sheet, student=self.student, assigned_by=self.teacher)
        response = self.client.post(
            reverse('assignment_group_update', args=[self.sheet.pk]),
            {'students': [self.student.pk, self.student2.pk],
             f'status_{self.student.pk}': Assignment.STATUS_RETURNED}, follow=True)
        shown = [str(m) for m in response.context['messages']]
        self.assertTrue(any('Новые ученики не добавлены: 1' in m for m in shown))
        self.assertFalse(any('сохранены' in m for m in shown))
        self.assertEqual(list(Assignment.objects.filter(worksheet=self.sheet)), [old])
        old.refresh_from_db()
        self.assertEqual(old.status, Assignment.STATUS_RETURNED)
        # Снять старую выдачу по-прежнему можно
        self.client.post(reverse('assignment_group_update', args=[self.sheet.pk]), {})
        self.assertFalse(Assignment.objects.filter(worksheet=self.sheet).exists())

    def test_old_assignment_still_works(self):
        old = Assignment.objects.create(
            worksheet=self.sheet, student=self.student, assigned_by=self.teacher)
        # Учитель: список выдач без новых учеников, массовый срок
        listing = self.client.get(reverse('assignment_list'))
        self.assertContains(listing, 'новых учеников добавить нельзя')
        self.client.post(reverse('assignment_bulk'), {
            'ids': [f'ordinary-{self.sheet.pk}'], 'action': 'apply',
            'due_action': 'set', 'due_at': '2026-11-01T12:00'})
        old.refresh_from_db()
        self.assertIsNotNone(old.due_at)
        self.assertEqual(Assignment.objects.filter(worksheet=self.sheet).count(), 1)
        # Ученик открывает работу
        self.client.login(username='student1', password='pass12345')
        page = self.client.get(reverse('assignment_detail', args=[old.pk]))
        self.assertContains(page, 'Найдите сумму корней')

    def test_worksheet_detail_shows_take_as_worksheet(self):
        page = self.client.get(reverse('worksheet_detail', args=[self.sheet.pk]))
        self.assertContains(page, 'её нельзя задать')
        self.assertContains(page, reverse('collection_use', args=[self.collection.pk]))
        self.assertNotContains(page, f'{reverse("assignment_create")}?worksheet={self.sheet.pk}')
        plain = self.client.get(reverse('worksheet_detail', args=[self.plain.pk]))
        self.assertContains(plain, f'{reverse("assignment_create")}?worksheet={self.plain.pk}')


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class CollectionToIndependentTests(TestCase):
    def setUp(self):
        self.author = make_teacher()
        self.other = make_teacher('teacher2')
        self.sheet = Worksheet.objects.create(title='§ 5. Виета', owner=self.author)
        self.task = Task.objects.create(text_latex='Задача', created_by=self.author)
        WorksheetItem.objects.create(worksheet=self.sheet, task=self.task, order=10)
        self.collection = Collection.objects.create(
            worksheet=self.sheet, source=Source.objects.create(title='Задачник'),
            locator='p5', is_published=True)
        self.url = reverse('collection_to_independent', args=[self.collection.pk])
        self.client.login(username='teacher2', password='pass12345')

    def test_other_teacher_builds_work_from_published_collection(self):
        detail = self.client.get(reverse('collection_detail', args=[self.collection.pk]))
        self.assertContains(detail, 'Самостоятельная по образцу')
        response = self.client.post(self.url)
        work = Work.objects.get(owner=self.other)
        self.assertRedirects(response, reverse('independentworks:edit', args=[work.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(work.source_worksheet, self.sheet)
        self.assertTrue(Candidate.objects.filter(position__work=work, task=self.task).exists())
        # «На основе …» ведёт на страницу подборки, а не в чужой конструктор
        edit = self.client.get(response.url)
        self.assertContains(edit, reverse('collection_detail', args=[self.collection.pk]))
        self.assertNotContains(edit, reverse('worksheet_detail', args=[self.sheet.pk]))

    def test_ziv_collection_goes_through_pair_preview(self):
        """Подборка Зива: не номер на каждую задачу, а пары вариантов
        в пулы — через мастер создания с предпросмотром."""
        self.sheet.items.all().delete()
        for variant in range(1, 5):
            WorksheetItem.objects.create(worksheet=self.sheet, rubric=f'Вариант {variant}',
                                         order=variant * 10)
            for number in (1, 2):
                task = Task.objects.create(text_latex=f'Задача {variant}/{number}')
                TaskSource.objects.create(source=self.collection.source, task=task, number=str(number),
                                          locator=f'sr/1/v{variant}/{number}')
                WorksheetItem.objects.create(worksheet=self.sheet, task=task, order=variant * 10 + number)
        response = self.client.post(self.url)
        create = reverse('independentworks:create')
        self.assertTrue(response.url.startswith(create + '?'))
        self.assertIn(f'collection={self.collection.pk}', response.url)
        self.assertFalse(Work.objects.exists())
        # Не-владелец опубликованной подборки проходит мастер до шаблона
        form = self.client.get(response.url)
        self.assertContains(form, f'<option value="{self.collection.pk}" selected>')
        data = {'title': '§ 5. Виета', 'source_mode': 'collection',
                'collection': self.collection.pk, 'pair': '3'}
        preview = self.client.post(create, data)
        self.assertTemplateUsed(preview, 'independentworks/source_preview.html')
        self.client.post(create, {**data, 'selection': preview.context['selection']})
        work = Work.objects.get(owner=self.other)
        self.assertEqual(
            [sorted(p.candidates.values_list('task__text_latex', flat=True)) for p in work.positions.all()],
            [['Задача 3/1', 'Задача 4/1'], ['Задача 3/2', 'Задача 4/2']])

    def test_unpublished_own_ziv_collection_reaches_create_flow(self):
        self.collection.is_published = False
        self.collection.save()
        TaskSource.objects.create(source=self.collection.source, task=self.task, number='1',
                                  locator='sr/1/v1/1')
        self.client.login(username='teacher1', password='pass12345')
        form = self.client.get(self.client.post(self.url).url)
        self.assertContains(form, f'<option value="{self.collection.pk}" selected>')
        self.client.login(username='teacher2', password='pass12345')
        foreign = self.client.get(reverse('independentworks:create'))
        self.assertNotIn(self.collection, foreign.context['collections'])

    def test_unpublished_foreign_collection_is_closed(self):
        self.collection.is_published = False
        self.collection.save()
        response = self.client.post(self.url)
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(Work.objects.exists())

    def test_disabled_feature(self):
        with override_settings(INDEPENDENT_WORKS_ENABLED=False):
            self.assertEqual(self.client.post(self.url).status_code, 404)
            detail = self.client.get(reverse('collection_detail', args=[self.collection.pk]))
            self.assertNotContains(detail, 'Самостоятельная по образцу')
        self.assertFalse(Work.objects.exists())
