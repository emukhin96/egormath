from django.test import TestCase
from django.urls import reverse

from problems.models import Source, Task
from problems.tests import make_student, make_teacher
from worksheets.cart import SESSION_KEY
from worksheets.models import Collection, Worksheet, WorksheetItem
from worksheets.tests import make_worksheet

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class CartTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.task = Task.objects.create(
            text_latex='Решите $x^2=4$.', answer_latex='$\\pm 2$',
            stars=1, created_by=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def _select(self, worksheet):
        session = self.client.session
        session[SESSION_KEY] = worksheet.pk
        session.save()

    def _active_tasks(self, worksheet):
        return list(worksheet.items.filter(
            deleted_at__isnull=True, task__isnull=False)
            .order_by('order').values_list('task_id', flat=True))

    def test_first_add_creates_worksheet(self):
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['in_cart'])
        self.assertEqual(data['count'], 1)
        worksheet = Worksheet.objects.get(pk=data['worksheet']['id'])
        self.assertEqual(worksheet.owner, self.teacher)
        self.assertEqual(worksheet.title, 'Новый листок')
        self.assertEqual(self.client.session[SESSION_KEY], worksheet.pk)
        self.assertEqual(self._active_tasks(worksheet), [self.task.pk])

    def test_add_to_selected_worksheet_appends(self):
        worksheet = make_worksheet(self.teacher)
        self._select(worksheet)
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        data = response.json()
        self.assertEqual(data['worksheet']['id'], worksheet.pk)
        self.assertEqual(data['count'], 3)
        self.assertEqual(self._active_tasks(worksheet)[-1], self.task.pk)
        # Повтор — не дубль
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        self.assertEqual(response.json()['count'], 3)
        self.assertIn('уже есть', response.json()['message'])

    def test_remove_and_restore(self):
        worksheet = make_worksheet(self.teacher)
        self._select(worksheet)
        self.client.post(reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        item = worksheet.items.get(task=self.task)
        response = self.client.post(
            reverse('cart_remove'), {'task_id': self.task.pk}, **XHR)
        data = response.json()
        self.assertFalse(data['in_cart'])
        self.assertEqual(data['count'], 2)
        item.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        # Повторное добавление восстанавливает тот же элемент
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        self.assertIn('возвращена', response.json()['message'])
        item.refresh_from_db()
        self.assertIsNone(item.deleted_at)
        self.assertEqual(worksheet.items.filter(task=self.task).count(), 1)

    def test_collection_worksheet_is_not_a_cart(self):
        backing = Worksheet.objects.create(title='Глава 1', owner=self.teacher)
        Collection.objects.create(
            worksheet=backing, source=Source.objects.create(title='Учебник'),
            locator='ch1', source_path=['Глава 1'])
        self._select(backing)
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        data = response.json()
        self.assertNotEqual(data['worksheet']['id'], backing.pk)
        self.assertFalse(backing.items.filter(task=self.task).exists())
        # Подборки нет и в списке выбора
        response = self.client.get(reverse('task_list'))
        self.assertNotIn(
            (backing.pk, 'Глава 1'), response.context['cart']['choices'])

    def test_foreign_or_deleted_worksheet_resets_session(self):
        other = make_teacher('teacher2')
        foreign = make_worksheet(other)
        self._select(foreign)
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        data = response.json()
        self.assertNotEqual(data['worksheet']['id'], foreign.pk)
        self.assertFalse(foreign.items.filter(task=self.task).exists())

        mine = make_worksheet(self.teacher)
        self._select(mine)
        mine.delete()
        response = self.client.get(reverse('task_list'))
        self.assertIsNone(response.context['cart']['worksheet'])
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_select_and_clear(self):
        worksheet = make_worksheet(self.teacher)
        response = self.client.post(
            reverse('cart_select'),
            {'worksheet': worksheet.pk, 'next': reverse('task_list')})
        self.assertRedirects(response, reverse('task_list'))
        self.assertEqual(self.client.session[SESSION_KEY], worksheet.pk)

        response = self.client.post(reverse('cart_select'), {'worksheet': 'new'})
        new_pk = self.client.session[SESSION_KEY]
        self.assertNotEqual(new_pk, worksheet.pk)
        self.assertEqual(Worksheet.objects.get(pk=new_pk).owner, self.teacher)

        self.client.post(reverse('cart_clear'))
        self.assertNotIn(SESSION_KEY, self.client.session)
        # Листок остаётся
        self.assertTrue(Worksheet.objects.filter(pk=new_pk).exists())

    def test_non_xhr_redirects_back_with_message(self):
        response = self.client.post(
            reverse('cart_add'),
            {'task_id': self.task.pk,
             'next': reverse('task_detail', args=[self.task.pk])})
        self.assertRedirects(
            response, reverse('task_detail', args=[self.task.pk]))
        response = self.client.get(reverse('task_detail', args=[self.task.pk]))
        self.assertContains(response, 'в листке')
        self.assertContains(response, 'data-in-cart="1"')

    def test_catalog_shows_button_state(self):
        worksheet = make_worksheet(self.teacher)
        self._select(worksheet)
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, '+ в листок')
        self.assertContains(response, 'data-cart-menu')
        self.assertIn(worksheet.title, response.content.decode())
        cart = response.context['cart']
        self.assertEqual(cart['count'], 2)
        self.assertEqual(
            cart['task_ids'], set(self._active_tasks(worksheet)))

    def test_variant_task_cannot_be_added(self):
        variant = Task.objects.create(
            text_latex='Локальная копия', variant_of=self.task,
            stars=0, created_by=self.teacher)
        response = self.client.post(
            reverse('cart_add'), {'task_id': variant.pk}, **XHR)
        self.assertEqual(response.status_code, 404)

    def test_student_has_no_cart(self):
        make_student(self.teacher)
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(reverse('dashboard'))
        self.assertIsNone(response.context['cart'])
        self.assertFalse(response.context['is_teacher'])
        self.assertNotContains(response, 'data-cart-menu')
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk})
        self.assertEqual(response.status_code, 403)

    def test_builder_remove_still_soft_deletes(self):
        """Рефакторинг helpers не сломал удаление в конструкторе."""
        worksheet = make_worksheet(self.teacher)
        item = worksheet.items.order_by('order').first()
        response = self.client.post(
            reverse('worksheet_remove_item', args=[worksheet.pk, item.pk]),
            **XHR)
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        self.assertEqual(WorksheetItem.objects.filter(
            worksheet=worksheet, deleted_at__isnull=True).count(), 1)
