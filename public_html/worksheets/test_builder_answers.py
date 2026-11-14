"""Рамки ответов конструктора подгружаются отдельным запросом у длинного листка
(быстродействие 11.2026, третий круг: worksheets/builder_rows.py
ANSWERS_INLINE_MAX, views.worksheet_answers, static/js/answers-toggle.js).

Короткий листок — рамки в HTML, как раньше. Длинный — в HTML их нет, а
``/worksheets/<pk>/answers/`` отдаёт владельцу ту же разметку по строкам;
чужому листок недоступен, как и конструктор.
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from problems.models import Task, TaskSubitem
from problems.tests import make_student, make_teacher

from .builder_rows import ANSWERS_INLINE_MAX
from .models import Worksheet, WorksheetItem
from .test_builder_rows import row_html
from .tests import make_rubric, make_worksheet

STATIC_JS = Path(settings.BASE_DIR) / 'static' / 'js'
TEMPLATES = Path(settings.BASE_DIR) / 'templates'


def answers_block(html):
    """Разметка рамки «Ответ / Решение» строки (от .ws-answers до блока масок)."""
    if 'class="ws-answers"' not in html:
        return ''
    return html.split('<div class="ws-answers"', 1)[1].split('<div data-worksheet-mask', 1)[0]


def squash(html):
    return re.sub(r'\s+', ' ', html).strip()


class BuilderAnswersTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1')
        # Длинный листок: на одну задачу больше порога, плюс рубрика,
        # задача без ответа и задача с подпунктами
        self.worksheet = make_worksheet(self.teacher, 'Длинный', n_tasks=ANSWERS_INLINE_MAX - 1)
        make_rubric(self.worksheet, 'Повторение', order=5)
        blank = Task.objects.create(text_latex='Без ответа $z$', created_by=self.teacher)
        self.blank_item = WorksheetItem.objects.create(worksheet=self.worksheet, task=blank, order=2000)
        parts = Task.objects.create(text_latex='Найдите', answer_latex='', solution_latex='Решение $s$',
                                    created_by=self.teacher)
        for index in range(2):
            TaskSubitem.objects.create(task=parts, order=index + 1, text_latex=f'$x_{index}$',
                                       answer_latex=f'{index}')
        self.parts_item = WorksheetItem.objects.create(worksheet=self.worksheet, task=parts, order=3000)
        self.items = [item for item in self.worksheet.ordered_items() if item.task_id]
        self.assertEqual(len(self.items), ANSWERS_INLINE_MAX + 1)
        self.url = reverse('worksheet_answers', args=[self.worksheet.pk])
        self.client.login(username='teacher1', password='pass12345')

    def page(self, pk=None):
        response = self.client.get(reverse('worksheet_detail', args=[pk or self.worksheet.pk]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_long_worksheet_html_has_no_answers_but_url(self):
        html = self.page()
        self.assertNotIn('class="ws-answers"', html)
        self.assertNotIn('<strong>Ответ:</strong>', html)
        self.assertIn(f'data-answers-url="{self.url}"', html)
        # Флаги строк не зависят от способа показа ответов
        self.assertIn('data-has-answer="1"', row_html(html, self.items[0]))
        self.assertIn('data-no-answer="1"', row_html(html, self.blank_item))

    def test_short_worksheet_keeps_inline_answers(self):
        short = make_worksheet(self.teacher, 'Короткий', n_tasks=3)
        html = self.page(short.pk)
        self.assertNotIn('data-answers-url', html)
        self.assertEqual(html.count('<div class="ws-answers" hidden>'), 3)
        # Ровно порог — ещё в HTML
        edge = make_worksheet(self.teacher, 'На пороге', n_tasks=ANSWERS_INLINE_MAX)
        html = self.page(edge.pk)
        self.assertNotIn('data-answers-url', html)
        self.assertEqual(html.count('<div class="ws-answers" hidden>'), ANSWERS_INLINE_MAX)

    def test_endpoint_returns_same_markup_as_inline(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        fetched = response.json()['items']
        # Строки без ответа и решения и рубрики не отдаются
        self.assertNotIn(str(self.blank_item.pk), fetched)
        self.assertEqual(len(fetched), len(self.items) - 1)
        self.assertIn('Ответ', response.content.decode())  # кириллица без \\u-кодов
        # Тот же листок с порогом выше — рамки в HTML; разметка совпадает построчно
        with mock.patch('worksheets.builder_rows.ANSWERS_INLINE_MAX', 10_000):
            html = self.page()
        self.assertNotIn('data-answers-url', html)
        for item in self.items:
            inline = answers_block(row_html(html, item))
            if item.pk == self.blank_item.pk:
                self.assertEqual(inline, '')
                continue
            self.assertTrue(fetched[str(item.pk)].startswith('<div class="ws-answers" hidden>'))
            self.assertEqual(squash(fetched[str(item.pk)]), squash('<div class="ws-answers"' + inline))
        parts = fetched[str(self.parts_item.pk)]
        self.assertIn('а)&nbsp;0', parts)
        self.assertIn('б)&nbsp;1', parts)
        self.assertIn('<strong>Решение:</strong>', parts)

    def test_items_filter(self):
        wanted = [self.items[0].pk, self.parts_item.pk]
        response = self.client.get(self.url, {'items': ','.join(str(pk) for pk in wanted) + ',x'})
        self.assertEqual(sorted(response.json()['items']), sorted(str(pk) for pk in wanted))
        self.assertEqual(self.client.get(self.url, {'items': ''}).json()['items'].keys().__len__(),
                         len(self.items) - 1)

    def test_only_get(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_foreign_worksheet_is_not_found(self):
        other = make_teacher('teacher2')
        foreign = make_worksheet(other, 'Чужой', n_tasks=1)
        self.assertEqual(self.client.get(reverse('worksheet_answers', args=[foreign.pk])).status_code, 404)
        # Как у конструктора
        self.assertEqual(self.client.get(reverse('worksheet_detail', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('worksheet_answers', args=[999_999])).status_code, 404)

    def test_student_and_anonymous_are_rejected(self):
        make_student(self.teacher, 'student1')
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response['Location'])
        self.client.login(username='student1', password='pass12345')
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_superuser_sees_any_worksheet(self):
        from django.contrib.auth.models import User
        from accounts.models import Profile
        root = User.objects.create_superuser('root', 'root@example.com', 'pass12345')
        Profile.objects.create(user=root, role=Profile.ROLE_TEACHER, base_editor=True)
        self.client.logout()
        self.client.login(username='root', password='pass12345')
        self.assertEqual(len(self.client.get(self.url).json()['items']), len(self.items) - 1)

    def test_queries_do_not_grow_with_rows(self):
        def count(worksheet):
            url = reverse('worksheet_answers', args=[worksheet.pk])
            self.client.get(url)
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(url)
            return len(ctx.captured_queries)
        small = make_worksheet(self.teacher, 'Малый', n_tasks=2)
        for item in small.ordered_items()[:1]:
            TaskSubitem.objects.create(task=item.task, order=1, text_latex='$a$', answer_latex='1')
        self.assertEqual(count(small), count(self.worksheet))


class AnswersToggleScriptTests(SimpleTestCase):
    """Договор шаблона и скрипта о подгрузке рамок."""

    def test_script_fetches_answers_by_data_attribute(self):
        src = (STATIC_JS / 'answers-toggle.js').read_text(encoding='utf-8')
        self.assertIn("list.getAttribute('data-answers-url')", src)
        self.assertIn('fetch(url', src)
        self.assertIn("data-answers-loaded", src)
        # Рамка встаёт на своё место — перед блоком масок
        self.assertIn("insertAdjacentHTML('beforebegin', html)", src)
        # Дорендер формул — ленивым API math.js
        self.assertIn('window.EgorMath.observe', src)
        self.assertIn("document.addEventListener('worksheet:updated', apply)", src)

    def test_template_marks_list_and_skips_empty_rows(self):
        src = (TEMPLATES / 'worksheets' / 'worksheet_detail.html').read_text(encoding='utf-8')
        self.assertIn('data-answers-url="{{ answers_url }}"', src)
        self.assertIn("{% if row.material %}{% include 'problems/_task_answers.html'", src)
        self.assertIn("answers-toggle.js' %}?v=5", src)
