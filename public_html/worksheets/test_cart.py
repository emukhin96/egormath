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

    def _fill(self, *tasks):
        session = self.client.session
        session[SESSION_KEY] = [t.pk for t in tasks]
        session.save()

    def _active_tasks(self, worksheet):
        return list(worksheet.items.filter(
            deleted_at__isnull=True, task__isnull=False)
            .order_by('order').values_list('task_id', flat=True))

    def test_add_is_virtual_and_deduplicated(self):
        before = Worksheet.objects.count()
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['in_cart'])
        self.assertEqual(data['count'], 1)
        # Листок от клика не создаётся
        self.assertEqual(Worksheet.objects.count(), before)
        self.assertEqual(self.client.session[SESSION_KEY], [self.task.pk])
        response = self.client.post(
            reverse('cart_add'), {'task_id': self.task.pk}, **XHR)
        self.assertEqual(response.json()['count'], 1)
        self.assertIn('уже в корзине', response.json()['message'])

    def test_remove(self):
        other = Task.objects.create(
            text_latex='Ещё', stars=1, created_by=self.teacher)
        self._fill(self.task, other)
        response = self.client.post(
            reverse('cart_remove'), {'task_id': self.task.pk}, **XHR)
        data = response.json()
        self.assertFalse(data['in_cart'])
        self.assertEqual(data['count'], 1)
        self.assertEqual(self.client.session[SESSION_KEY], [other.pk])
        self.client.post(reverse('cart_remove'), {'task_id': other.pk}, **XHR)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_create_worksheet_from_cart(self):
        other = Task.objects.create(
            text_latex='Ещё', stars=1, created_by=self.teacher)
        self._fill(other, self.task)
        response = self.client.post(reverse('cart_create'))
        worksheet = Worksheet.objects.get(owner=self.teacher)
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[worksheet.pk]))
        self.assertEqual(worksheet.title, 'Новый листок')
        # Порядок — как добавляли
        self.assertEqual(self._active_tasks(worksheet), [other.pk, self.task.pk])
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_create_with_empty_cart_makes_nothing(self):
        response = self.client.post(
            reverse('cart_create'), {'next': reverse('task_list')})
        self.assertRedirects(response, reverse('task_list'))
        self.assertFalse(Worksheet.objects.filter(owner=self.teacher).exists())

    def test_append_to_existing_worksheet(self):
        worksheet = make_worksheet(self.teacher)
        existing = self._active_tasks(worksheet)[0]
        self._fill(self.task, Task.objects.get(pk=existing))
        response = self.client.post(
            reverse('cart_append'), {'worksheet': worksheet.pk})
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[worksheet.pk]))
        # Новая — в конец, уже имеющаяся — без дубля
        self.assertEqual(self._active_tasks(worksheet)[-1], self.task.pk)
        self.assertEqual(len(self._active_tasks(worksheet)), 3)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_append_restores_soft_deleted_item(self):
        worksheet = make_worksheet(self.teacher)
        item = worksheet.items.order_by('order').first()
        self.client.post(
            reverse('worksheet_remove_item', args=[worksheet.pk, item.pk]),
            **XHR)
        self._fill(item.task)
        self.client.post(reverse('cart_append'), {'worksheet': worksheet.pk})
        item.refresh_from_db()
        self.assertIsNone(item.deleted_at)
        self.assertEqual(worksheet.items.filter(task=item.task).count(), 1)

    def test_cannot_append_to_collection_or_foreign_worksheet(self):
        backing = Worksheet.objects.create(title='Глава 1', owner=self.teacher)
        Collection.objects.create(
            worksheet=backing, source=Source.objects.create(title='Учебник'),
            locator='ch1', source_path=['Глава 1'])
        foreign = make_worksheet(make_teacher('teacher2'))
        self._fill(self.task)
        for target in (backing, foreign):
            response = self.client.post(
                reverse('cart_append'), {'worksheet': target.pk})
            self.assertEqual(response.status_code, 404)
            self.assertFalse(target.items.filter(task=self.task).exists())
        # Корзина при этом не потеряна
        self.assertEqual(self.client.session[SESSION_KEY], [self.task.pk])
        # Подборки нет и в списке выбора
        response = self.client.get(reverse('task_list'))
        self.assertNotIn(
            (backing.pk, 'Глава 1'), response.context['cart']['choices'])

    def test_clear(self):
        self._fill(self.task)
        self.client.post(reverse('cart_clear'))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(Worksheet.objects.filter(owner=self.teacher).exists())

    def test_non_xhr_redirects_back_with_message(self):
        response = self.client.post(
            reverse('cart_add'),
            {'task_id': self.task.pk,
             'next': reverse('task_detail', args=[self.task.pk])})
        self.assertRedirects(
            response, reverse('task_detail', args=[self.task.pk]))
        response = self.client.get(reverse('task_detail', args=[self.task.pk]))
        self.assertContains(response, 'data-in-cart="1"')

    def test_plus_button_on_catalog_collection_and_builder(self):
        self._fill(self.task)
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'class="cart-btn is-in-cart"')
        self.assertContains(response, 'col-cart')
        self.assertContains(response, 'data-cart-menu')
        cart = response.context['cart']
        self.assertEqual(cart['count'], 1)
        self.assertEqual(cart['task_ids'], {self.task.pk})

        worksheet = make_worksheet(self.teacher)
        response = self.client.get(
            reverse('worksheet_detail', args=[worksheet.pk]))
        self.assertContains(response, 'data-cart-form', count=2)

        backing = Worksheet.objects.create(title='Глава 1', owner=self.teacher)
        WorksheetItem.objects.create(worksheet=backing, task=self.task, order=10)
        collection = Collection.objects.create(
            worksheet=backing, source=Source.objects.create(title='Учебник'),
            locator='ch1', source_path=['Глава 1'])
        response = self.client.get(
            reverse('collection_detail', args=[collection.pk]))
        self.assertContains(response, 'data-cart-form', count=1)
        self.assertContains(response, 'class="cart-btn is-in-cart"')

    def test_variant_task_cannot_be_added(self):
        variant = Task.objects.create(
            text_latex='Локальная копия', variant_of=self.task,
            stars=0, created_by=self.teacher)
        response = self.client.post(
            reverse('cart_add'), {'task_id': variant.pk}, **XHR)
        self.assertEqual(response.status_code, 404)
        # …и не показывает «+» в конструкторе
        worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.create(worksheet=worksheet, task=variant, order=99)
        response = self.client.get(
            reverse('worksheet_detail', args=[worksheet.pk]))
        self.assertContains(response, 'data-cart-form', count=2)

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
