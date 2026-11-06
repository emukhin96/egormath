"""Экраны листков после ревизии интерфейса 03.11 (L1–L4).

- L1: в «Моих листках» листок — одна строка, класс и темы текстом,
  действия — в меню «⋯», автор — только у чужих листков.
- L2: в шапке списка нет счётчиков, «Импорт из .tex» и «Сверка корпуса» —
  в «⋯», заливная одна — «Создать листок».
- L3: у задачи в конструкторе нет стрелок ↑↓ и строки ссылок,
  «Выше»/«Ниже» и остальное — в «⋯», «+» в корзину — всегда.
- L4: в шапке конструктора «PDF» и «Выдать», остальное — в «⋯»,
  без боковой панели; «Кому выдан» — в блоке «Ученикам».
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from assignments.models import Assignment
from problems.models import Source
from problems.models import Task
from problems.tests import make_teacher
from worksheets.models import Collection
from worksheets.models import Worksheet
from worksheets.models import WorksheetItem


class WorksheetListScreenTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1')
        self.client.login(username='teacher1', password='pass12345')
        self.sheet = Worksheet.objects.create(
            owner=self.teacher, title='Квадратные уравнения', grade=8,
            comment='corpus:8 класс/kvadr')

    def test_one_row_per_worksheet_and_actions_in_menu(self):
        response = self.client.get(reverse('worksheet_list'))
        html = response.content.decode()
        self.assertEqual(html.count('class="ws-list-row"'), 1)
        self.assertNotContains(response, 'worksheet-action-row')
        # Класс текстом, без выпадающего списка в строке
        self.assertNotContains(response, 'aria-label="Класс листка"')
        # Путь корпуса — подсказкой названия
        self.assertContains(response, 'title="corpus:8 класс/kvadr"')
        menu = html[html.index('class="ws-list-row"'):]
        for label in ('>PDF<', '>Дублировать<', '>Прогресс учеников<', '>Удалить<'):
            self.assertIn(label, menu)
        self.assertIn('more-menu on-hover', menu)

    def test_no_counters_and_rare_actions_in_head_menu(self):
        response = self.client.get(reverse('worksheet_list'))
        html = response.content.decode()
        self.assertNotContains(response, 'Листков:')
        self.assertNotContains(response, '1 листок')
        head = html[html.index('class="page-actions"'):html.index('id="worksheet-filters"')]
        self.assertIn('more-menu is-head', head)
        self.assertIn('Импорт из .tex', head)
        self.assertEqual(head.count('class="btn'), 1)

    def test_author_only_for_foreign_worksheets(self):
        root = User.objects.create_superuser('root', 'root@example.com', 'pass12345')
        Profile.objects.create(user=root, role=Profile.ROLE_TEACHER)
        Worksheet.objects.create(owner=root, title='Свой листок')
        self.client.login(username='root', password='pass12345')
        html = self.client.get(reverse('worksheet_list')).content.decode()
        self.assertEqual(html.count('class="ws-list-author"'), 1)
        self.assertIn('class="ws-list-author">Иван Учителев<', html)


class WorksheetBuilderScreenTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1')
        self.client.login(username='teacher1', password='pass12345')
        self.sheet = Worksheet.objects.create(owner=self.teacher, title='Листок')
        for n in range(2):
            task = Task.objects.create(text_latex=f'Задача {n}', created_by=self.teacher)
            WorksheetItem.objects.create(worksheet=self.sheet, task=task, order=n)

    def page(self, sheet=None):
        return self.client.get(reverse('worksheet_detail', args=[(sheet or self.sheet).pk]))

    def test_task_row_keeps_cart_and_moves_rest_to_menu(self):
        response = self.page()
        html = response.content.decode()
        self.assertNotContains(response, '>↑<')
        self.assertNotContains(response, '>↓<')
        self.assertEqual(html.count('class="cart-btn'), 2)
        self.assertEqual(html.count('aria-label="Действия с задачей"'), 2)
        # Первой задаче — только «Ниже», последней — только «Выше»
        self.assertEqual(html.count('>Выше<'), 1)
        self.assertEqual(html.count('>Ниже<'), 1)
        for label in ('Сбросить звёзды', 'Только полный ответ', 'Дублировать локально',
                      'Клон рядом', 'Скопировать картинкой', 'Видимость для учеников',
                      'Убрать из листка'):
            self.assertContains(response, label)
        # Режим ответа — пометкой, которую CSS показывает только у «только полный»
        self.assertContains(response, 'ws-full-only-note')

    def test_head_actions_and_no_sidebar(self):
        response = self.page()
        html = response.content.decode()
        head = html[html.index('class="page-actions"'):html.index('id="title-inline-form"')]
        self.assertIn(f'{reverse("assignment_create")}?worksheet={self.sheet.pk}', head)
        self.assertIn('>Выдать<', head)
        self.assertIn('>PDF<', head)
        self.assertIn('more-menu is-head', head)
        for label in ('Свойства', 'Презентация', '.tex', 'В подборки'):
            self.assertIn(label, head)
        self.assertNotContains(response, 'class="ws-toolbar"')
        self.assertNotContains(response, 'sidebar-section')

    def test_recipients_block_in_content(self):
        student = User.objects.create_user('student1', password='pass12345')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        assignment = Assignment.objects.create(worksheet=self.sheet, student=student)
        response = self.page()
        self.assertContains(response, 'id="worksheet-recipients"')
        self.assertContains(response, reverse(
            'worksheet_recipient_visibility', args=[self.sheet.pk, 'assignment', assignment.pk]))

    def test_collection_note_is_one_line_with_take_action(self):
        source = Source.objects.create(title='Задачник')
        collection = Collection.objects.create(source=source, worksheet=self.sheet)
        response = self.page()
        self.assertContains(response, 'Это подборка из каталога: правки видят все.')
        self.assertContains(response, reverse('collection_use', args=[collection.pk]))
        self.assertNotContains(response, 'backing-листок')
        # Подборку не выдают — «Выдать» в шапке нет
        html = response.content.decode()
        head = html[html.index('class="page-actions"'):html.index('id="title-inline-form"')]
        self.assertNotIn('>Выдать<', head)
