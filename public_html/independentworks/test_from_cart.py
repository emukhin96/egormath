"""Корзина → самостоятельная: номера в конце, похожие в один номер, блоки, дубли."""
from django.test import TestCase, override_settings
from django.urls import reverse

from problems.models import Source, Task, TaskBlock, TaskSource, TaskSubitem
from problems.tests import make_teacher
from worksheets.cart import SESSION_KEY

from .analogs import similar_groups
from .models import Candidate, Family, FamilyMember, Position, Work


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class CartToIndependentTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.ziv = Source.objects.create(title='Зив 8')
        # Пара вариантов ЗИВ: v1 и v2 одного номера — одна семья
        self.viet_a = self._task('Сумма корней $x^2-7x+10=0$', self.ziv, 'sr/3/v1/2')
        self.viet_b = self._task('Сумма корней $x^2+3x-18=0$', self.ziv, 'sr/3/v2/2')
        self.plain = self._task('Периметр 30, площадь 56')
        # Вручную созданные аналоги — семья Family
        self.manual_a = self._task('Неполное $3x^2-12=0$')
        self.manual_b = self._task('Неполное $5x^2-45=0$')
        family = Family.objects.create(key='manual:1', title='Неполные')
        for task in (self.manual_a, self.manual_b):
            FamilyMember.objects.create(family=family, task=task)
        self.url = reverse('cart_to_independent')

    def _task(self, text, source=None, locator=None):
        task = Task.objects.create(text_latex=text, created_by=self.teacher)
        if source:
            TaskSource.objects.create(task=task, source=source, number=locator.rsplit('/', 1)[-1],
                                      locator=locator)
        return task

    def _fill(self, *tasks):
        session = self.client.session
        session[SESSION_KEY] = [t.pk for t in tasks]
        session.save()

    def _numbers(self, work):
        return [list(p.candidates.order_by('pk').values_list('task_id', flat=True))
                for p in work.positions.all()]

    def test_similar_groups(self):
        groups = similar_groups([self.viet_a.pk, self.plain.pk, self.manual_a.pk,
                                 self.viet_b.pk, self.manual_b.pk])
        self.assertEqual(groups, {self.viet_a.pk: 0, self.viet_b.pk: 0,
                                  self.manual_a.pk: 1, self.manual_b.pk: 1})

    def test_new_work_groups_similar_in_order_of_first_appearance(self):
        self._fill(self.viet_a, self.manual_a, self.plain, self.viet_b, self.manual_b)
        response = self.client.post(self.url, {'target': 'new', 'title': 'С-3', 'group_similar': '1'})
        work = Work.objects.get(owner=self.teacher)
        self.assertEqual(work.title, 'С-3')
        self.assertEqual(self._numbers(work), [
            [self.viet_a.pk, self.viet_b.pk], [self.manual_a.pk, self.manual_b.pk], [self.plain.pk]])
        self.assertRedirects(response, reverse('independentworks:edit', args=[work.pk]),
                             fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)
        page = self.client.get(response.url)
        self.assertContains(page, 'Добавлено 3 номера из корзины')
        self.assertContains(page, 'iw-new', count=3)
        # Подсветка — один раз: ни перезагрузка, ни POST-действие её не повторяют
        self.assertNotContains(self.client.get(response.url), 'iw-new')
        position = work.positions.first()
        after = self.client.post(response.url, {'action': 'text', 'position': position.pk, 'text': ''}, follow=True)
        self.assertNotContains(after, 'iw-new')

    def test_without_grouping_each_task_is_a_number(self):
        self._fill(self.viet_a, self.viet_b, self.plain)
        self.client.post(self.url, {'target': 'new'})
        work = Work.objects.get()
        self.assertEqual(work.title, 'Новая самостоятельная')
        self.assertEqual(self._numbers(work), [[self.viet_a.pk], [self.viet_b.pk], [self.plain.pk]])

    def test_existing_work_appends_and_skips_duplicates(self):
        work = Work.objects.create(owner=self.teacher, title='Старая')
        first = Position.objects.create(work=work, order=1)
        Candidate.objects.create(position=first, task=self.plain)
        self._fill(self.plain, self.manual_a, self.manual_b)
        response = self.client.post(self.url, {'target': 'existing', 'work': work.pk, 'group_similar': '1'})
        self.assertEqual(self._numbers(work), [[self.plain.pk], [self.manual_a.pk, self.manual_b.pk]])
        page = self.client.get(response.url)
        self.assertContains(page, 'пропущено 1: уже есть в самостоятельной')

    def test_mismatched_parts_are_allowed_in_one_number(self):
        TaskSubitem.objects.create(task=self.viet_b, text_latex='а', order=1)
        TaskSubitem.objects.create(task=self.viet_b, text_latex='б', order=2)
        self._fill(self.viet_a, self.viet_b)
        self.client.post(self.url, {'target': 'new', 'group_similar': '1'})
        work = Work.objects.get()
        self.assertEqual(self._numbers(work), [[self.viet_a.pk, self.viet_b.pk]])
        self.assertContains(self.client.get(reverse('independentworks:edit', args=[work.pk])),
                            'Разное число подпунктов')

    def test_block_takes_consecutive_numbers(self):
        block = TaskBlock.objects.create(source=Source.objects.create(title='ОГЭ'), key='b', title='Участок', size=2)
        first, second = [Task.objects.create(text_latex=f'Вопрос {n}', block=block, block_position=n)
                         for n in (1, 2)]
        self._fill(self.plain, first, second, self.viet_a)
        self.client.post(self.url, {'target': 'new', 'group_similar': '1'})
        work = Work.objects.get()
        self.assertEqual(self._numbers(work), [[self.plain.pk], [first.pk], [second.pk], [self.viet_a.pk]])

    def test_foreign_work_is_404_and_cart_kept(self):
        other = make_teacher('teacher2')
        work = Work.objects.create(owner=other, title='Чужая')
        self._fill(self.plain)
        response = self.client.post(self.url, {'target': 'existing', 'work': work.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(work.positions.exists())
        self.assertEqual(self.client.session[SESSION_KEY], [self.plain.pk])

    def test_disabled_feature(self):
        self._fill(self.plain)
        with override_settings(INDEPENDENT_WORKS_ENABLED=False):
            self.assertEqual(self.client.post(self.url, {'target': 'new'}).status_code, 404)
            menu = self.client.get(reverse('task_list'))
            self.assertNotContains(menu, 'Добавить в самостоятельную')
            self.assertNotContains(menu, 'Новая самостоятельная')
        self.assertFalse(Work.objects.exists())

    def test_menu_lists_tasks_with_family_dots(self):
        Work.objects.create(owner=self.teacher, title='Контрольная С-1')
        self._fill(self.viet_a, self.plain, self.viet_b)
        page = self.client.get(reverse('task_list'))
        self.assertContains(page, 'Корзина · 3 задачи')
        self.assertContains(page, 'Зив 8, №2')
        self.assertContains(page, f'Задача #{self.plain.pk}')
        self.assertContains(page, 'cart-fam cart-fam-1', count=2)
        self.assertContains(page, 'Контрольная С-1')
        self.assertContains(page, 'name="group_similar" value="1" form="cart-iw-form" checked')
        panel = self.client.get(reverse('cart_panel'), {'next': '/problems/'})
        self.assertContains(panel, 'value="/problems/"')
        self.assertContains(panel, 'data-cart-remove', count=3)

    def test_menu_shows_first_eight_and_more(self):
        tasks = [Task.objects.create(text_latex=f'Задача номер {n}') for n in range(10)]
        self._fill(*tasks)
        page = self.client.get(reverse('task_list'))
        self.assertContains(page, 'data-cart-remove', count=8)
        self.assertContains(page, 'и ещё 2')
