"""Панель действий с задачей (includes/task_actions.html, ROADMAP 11.2026,
п. 3): картинкой, в корзину, открыть задачу — на экранах, где учитель видит
задачу. «Открыть» и корзина — только для задачи, видимой учителю
(accounts.permissions.can_view_task), у локальной копии — её карточка без
корзины."""
import re

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.permissions import can_view_task, visible_tasks
from problems.models import Source, Task, TaskProposal
from problems.test_permissions import shared_task
from problems.tests import make_invited_teacher, make_student, make_teacher
from worksheets.models import Collection, Worksheet, WorksheetItem
from .models import Assignment, Submission

PANEL = 'data-task-actions'


def panels(html):
    return len(re.findall(PANEL, html))


def detail(task):
    return reverse('task_detail', args=[task.pk])


class IncludeVisibilityTests(TestCase):
    """Сам include: кому какие кнопки."""

    def setUp(self):
        self.editor = make_teacher('editor')
        self.guest = make_invited_teacher('guest')
        self.other = make_invited_teacher('guest2')
        self.shared = shared_task(self.editor)
        self.own = Task.new_for(self.guest, text_latex='Моя задача гостя')
        self.foreign = Task.new_for(self.other, text_latex='Чужая задача')
        self.copy = self.shared.make_variant(self.guest)

    def render(self, user, task, **extra):
        request = RequestFactory().get('/')
        request.user = user
        request.session = {}
        return render_to_string('includes/task_actions.html', {'task': task, **extra}, request=request)

    def test_can_view_task_matches_visible_tasks(self):
        for user in (self.editor, self.guest, self.other):
            visible = set(visible_tasks(user))
            for task in (self.shared, self.own, self.foreign, self.copy):
                self.assertEqual(can_view_task(user, task), task in visible, (user, task))

    def test_guest_gets_no_link_to_foreign_personal_task(self):
        html = self.render(self.guest, self.foreign, compact=True)
        self.assertIn(PANEL, html)
        self.assertRegex(html, r'data-task-png[\s>]')
        self.assertNotIn(detail(self.foreign), html)
        # Корзина взяла бы задачу из cart_tasks и ответила бы 404
        self.assertNotIn('data-cart-js', html)

    def test_guest_shared_and_own(self):
        for task in (self.shared, self.own):
            html = self.render(self.guest, task, compact=True)
            self.assertIn(f'href="{detail(task)}"', html)
            self.assertIn('target="_blank"', html)
            self.assertIn('data-cart-js', html)
            # Без вложенной формы: страница проверки целиком лежит в <form>,
            # вложенная форма отправила бы её («Проверка сохранена»)
            self.assertNotIn('<form', html)

    def test_local_copy_opens_itself_without_cart(self):
        html = self.render(self.guest, self.copy)
        self.assertIn(f'href="{detail(self.copy)}"', html)
        self.assertNotIn(f'href="{detail(self.shared)}"', html)
        self.assertNotIn('data-cart-js', html)

    def test_editor_opens_foreign_task(self):
        self.assertIn(f'href="{detail(self.foreign)}"', self.render(self.editor, self.foreign))

    def test_task_in_own_worksheet_is_visible(self):
        sheet = Worksheet.objects.create(title='Листок гостя', owner=self.guest)
        WorksheetItem.objects.create(worksheet=sheet, task=self.foreign, order=10)
        self.assertIn(f'href="{detail(self.foreign)}"', self.render(self.guest, self.foreign))

    def test_full_and_compact_variants(self):
        full = self.render(self.guest, self.shared)
        self.assertIn('Картинкой', full)
        self.assertIn('+ В корзину', full)
        self.assertIn('data-label-in="✓ В корзине"', full)
        compact = self.render(self.guest, self.shared, compact=True)
        self.assertIn('is-compact', compact)
        self.assertIn('task-png-btn', compact)
        self.assertNotIn('Картинкой', compact)

    def test_switches_and_custom_link(self):
        html = self.render(self.guest, self.shared, no_png=True, no_cart=True, link='/x/')
        self.assertNotRegex(html, r'data-task-png[\s>]')
        self.assertNotIn('data-cart-js', html)
        self.assertIn('href="/x/"', html)
        self.assertNotIn('href="/x/"', self.render(self.guest, self.foreign, link='/x/'))

    def test_student_gets_nothing(self):
        student = make_student(self.editor)
        self.assertEqual(self.render(student, self.shared).strip(), '')


class ScreensTests(TestCase):
    """Ключевые экраны учителя рендерят панель (и cart.js — один раз, из base.html)."""

    def setUp(self):
        self.teacher = make_teacher('teacher')
        self.worksheet = Worksheet.objects.create(title='Дроби', owner=self.teacher)
        self.task = Task.objects.create(text_latex='Сократите $\\frac{6}{8}$.', created_by=self.teacher,
                                        is_shared=True, answer_mask='{{number: 0.75}}')
        self.item = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=10)
        self.student = make_student(self.teacher)
        self.assignment = Assignment.objects.create(worksheet=self.worksheet, student=self.student,
                                                    assigned_by=self.teacher)
        Submission.objects.create(assignment=self.assignment, task=self.task, answer_json={'s1': '0.75'})
        self.client.force_login(self.teacher)

    def get(self, name, *args, **params):
        response = self.client.get(reverse(name, args=args), params)
        self.assertEqual(response.status_code, 200, name)
        return response.content.decode()

    def assert_panel(self, html, name):
        self.assertGreaterEqual(panels(html), 1, name)
        self.assertIn(detail(self.task), html, name)

    def test_assignment_screens(self):
        pages = {
            'review_assignment': self.get('review_assignment', self.assignment.pk),
            'review_tasks': self.get('assignment_review_queue', self.worksheet.pk),
            'task_window': self.get('worksheet_task_window', self.worksheet.pk, self.item.pk),
            'task_attempts': self.get('task_attempts', self.assignment.pk, self.task.pk),
            'task_class': self.get('assignment_item_class', self.worksheet.pk, self.item.pk),
            'timeline': self.get('assignment_timeline', self.assignment.pk),
        }
        for name, html in pages.items():
            self.assert_panel(html, name)
        # Окно задачи — панель с подписями вместо прежней «Задача в базе»
        self.assertIn('Картинкой', pages['task_window'])
        self.assertNotIn('Задача в базе', pages['task_window'])
        # Корзина одна на страницу: cart.js подключает только base.html
        self.assertEqual(pages['review_assignment'].count('js/cart.js'), 1)

    def test_boards_screens(self):
        self.assert_panel(self.get('worksheet_boards', self.worksheet.pk, task=self.task.pk), 'boards')
        self.assert_panel(self.get('worksheet_boards_tasks', self.worksheet.pk), 'boards_tasks')
        self.assert_panel(self.get('worksheet_boards_peek', self.worksheet.pk, self.assignment.pk, self.task.pk),
                          'boards_peek')

    def test_proposal_screens(self):
        guest = make_invited_teacher('guest')
        proposal = TaskProposal.objects.create(task=self.task, author=guest, message='Опечатка')
        self.assertGreaterEqual(panels(self.get('proposal_detail', proposal.pk)), 1)
        self.client.force_login(guest)
        self.assert_panel(self.get('task_propose', self.task.pk), 'propose')

    def test_builder_finder(self):
        other = Task.objects.create(text_latex='Найдите долю пирога', created_by=self.teacher, is_shared=True)
        html = self.get('worksheet_detail', self.worksheet.pk, q='пирога')
        finder = html.split('id="finder-results"', 1)[1]
        self.assertIn(detail(other), finder)
        self.assertIn(PANEL, finder)


class CollectionRowsTests(TestCase):
    """Подборка другого учителя: у его личной задачи — картинка, но без ссылки
    и корзины; у общей — всё."""

    def setUp(self):
        self.editor = make_teacher('editor')
        self.author = make_invited_teacher('author')
        self.guest = make_invited_teacher('guest')
        sheet = Worksheet.objects.create(title='Подборка автора', owner=self.author)
        self.shared = shared_task(self.editor, 'Общая задача подборки')
        self.private = Task.new_for(self.author, text_latex='Личная задача автора')
        WorksheetItem.objects.create(worksheet=sheet, task=self.shared, order=10)
        WorksheetItem.objects.create(worksheet=sheet, task=self.private, order=20)
        self.collection = Collection.objects.create(
            worksheet=sheet, source=Source.objects.create(title='Задачник'), locator='p1', is_published=True)

    def test_guest_sees_link_only_to_visible(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('collection_detail', args=[self.collection.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertGreaterEqual(panels(html), 2)
        self.assertIn(detail(self.shared), html)
        self.assertNotIn(f'href="{detail(self.private)}"', html)
