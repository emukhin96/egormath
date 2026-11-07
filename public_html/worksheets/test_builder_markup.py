"""Разметка строк конструктора после облегчения (быстродействие 11.2026).

Диалог видимости — один на страницу, его данные в атрибутах строки; действия
меню «⋯» — кнопки с formaction у общей формы; иконки — символы с <use>;
тумблер «только полный ответ» — чекбокс без своей формы.
"""
import re

from django.test import TestCase
from django.urls import reverse

from accounts.models import StudentGroup
from assignments.models import Assignment
from problems.tests import make_student, make_teacher

from .models import ShareLink
from .tests import make_rubric, make_worksheet


def items_block(html):
    """HTML списка задач: от #ws-items до плашки «Задач пока нет»."""
    return html.split('id="ws-items"', 1)[1].split('id="ws-empty"', 1)[0]


class BuilderMarkupTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1')
        self.worksheet = make_worksheet(self.teacher, n_tasks=3)
        make_rubric(self.worksheet, 'Повторение', order=5)
        self.items = list(self.worksheet.ordered_items())
        self.tasks = [item for item in self.items if item.task_id]
        self.link = ShareLink.objects.create(worksheet=self.worksheet)
        self.group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        self.assignments = []
        for name in ('student1', 'student2'):
            student = make_student(self.teacher, name)
            self.group.students.add(student)
            assignment = Assignment.objects.create(
                worksheet=self.worksheet, student=student,
                assigned_by=self.teacher, recipient_origin_known=True)
            assignment.source_groups.add(self.group)
            self.assignments.append(assignment)
        self.client.login(username='teacher1', password='pass12345')

    def page(self):
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def row(self, html, item):
        start = html.index(f'data-id="{item.pk}"')
        return html[start:html.index('\n', start)]

    def test_one_visibility_dialog_with_row_data(self):
        html = self.page()
        self.assertEqual(html.count('id="ws-visibility-dialog"'), 1)
        self.assertNotIn('id="vis-', html)
        # Списки галочек — по одному на страницу, без состояния строки
        self.assertEqual(html.count('name="hide_links"'), 1)
        self.assertEqual(html.count('name="hide_groups"'), 1)
        self.assertEqual(html.count('name="hide_assignments"'), 2)
        for item in self.tasks:
            row = self.row(html, item)
            self.assertIn(
                'data-vis-url="%s"' % reverse(
                    'worksheet_item_visibility', args=[self.worksheet.pk, item.pk]),
                row)
            self.assertIn('data-hidden-links=""', row)
        self.assertNotIn('data-vis-url', self.row(html, self.items[0]))
        self.assertEqual(html.count("data-vis-open"), len(self.tasks))

    def test_hidden_state_lives_in_row_attributes(self):
        first = self.tasks[0]
        self.link.hidden_items.add(first)
        for assignment in self.assignments:
            assignment.hidden_items.add(first)
        html = self.page()
        row = self.row(html, first)
        self.assertIn(f'data-hidden-links="{self.link.pk}"', row)
        self.assertIn(f'data-hidden-groups="{self.group.pk}"', row)
        self.assertRegex(row, r'data-hidden-assignments="(%d,%d|%d,%d)"' % (
            self.assignments[0].pk, self.assignments[1].pk,
            self.assignments[1].pk, self.assignments[0].pk))
        self.assertIn('data-hidden-links=""', self.row(html, self.tasks[1]))
        # Перечёркнутый глаз — только у скрытой, иконка через символ
        self.assertEqual(html.count('vis-btn vis-on'), 1)
        self.assertEqual(html.count('<use href="#ws-icon-eye-off"/>'), 1)
        self.assertEqual(html.count('id="ws-icon-eye-off"'), 1)

    def test_row_actions_share_one_form(self):
        html = self.page()
        block = items_block(html)
        self.assertEqual(html.count('id="ws-row-form"'), 1)
        self.assertEqual(html.count('id="ws-row-action-form"'), 1)
        # В строках остаются только формы автосохранения (настройки задачи,
        # рубрика, текст) и кнопка корзины
        self.assertEqual(block.count('<form'),
                         block.count('data-autosave=') + block.count('data-cart-form'))
        self.assertEqual(block.count('data-autosave='), len(self.items))
        middle = self.tasks[1]
        for direction in ('up', 'down'):
            self.assertIn(
                'form="ws-row-form" formaction="%s"' % reverse(
                    'worksheet_move_item', args=[self.worksheet.pk, middle.pk, direction]),
                block)
        self.assertIn(
            'form="ws-row-action-form" formaction="%s" class="is-danger"' % reverse(
                'worksheet_remove_item', args=[self.worksheet.pk, middle.pk]),
            block)
        duplicate = reverse('task_duplicate', args=[middle.task.pk])
        context = f'{duplicate}?worksheet={self.worksheet.pk}&amp;item={middle.pk}'
        self.assertEqual(block.count(f'formaction="{context}"'), 2)
        self.assertIn(f'formaction="{context}" name="standalone" value="1"', block)
        # Первая строка — без «Выше», последняя — без «Ниже»
        self.assertNotIn(
            reverse('worksheet_move_item', args=[self.worksheet.pk, self.items[0].pk, 'up']),
            block)
        self.assertNotIn(
            reverse('worksheet_move_item', args=[self.worksheet.pk, self.items[-1].pk, 'down']),
            block)

    def test_menu_icon_is_a_symbol(self):
        html = self.page()
        self.assertEqual(html.count('id="ws-icon-more"'), 1)
        self.assertEqual(items_block(html).count('<use href="#ws-icon-more"/>'),
                         len(self.items))
        self.assertNotIn('<circle', items_block(html))

    def test_answer_policy_toggle_without_form(self):
        self.tasks[0].task.full_answer_only = True
        self.tasks[0].task.save(update_fields=['full_answer_only'])
        html = self.page()
        block = items_block(html)
        self.assertNotIn('name="block" value="answer_policy"', block)
        toggles = re.findall(
            r'name="full_answer_only" data-worksheet="(\d+)" data-item="(\d+)"( checked)?', block)
        self.assertEqual(
            toggles, [(str(self.worksheet.pk), str(item.pk),
                       ' checked' if item is self.tasks[0] else '')
                      for item in self.tasks])

    def test_visibility_endpoint_matches_dialog_fields(self):
        first = self.tasks[0]
        url = reverse('worksheet_item_visibility', args=[self.worksheet.pk, first.pk])
        response = self.client.post(url, {
            'hide_links': [self.link.pk], 'hide_groups': [self.group.pk]},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['ok'])
        self.assertEqual(set(self.link.hidden_items.all()), {first})
        for assignment in self.assignments:
            self.assertEqual(set(assignment.hidden_items.all()), {first})
        row = self.row(self.page(), first)
        self.assertIn(f'data-hidden-groups="{self.group.pk}"', row)
