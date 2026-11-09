"""Строки конструктора считаются в Python, формулы рендерятся лениво
(быстродействие 11.2026, второй круг: worksheets/builder_rows.py, math.js).

Разметка строки не изменилась — проверяем её ключевые места: адреса действий,
корзину, звёзды, подпункты, запрет правки общей задачи у приглашённого; число
SQL-запросов не растёт с числом строк; числа в строках не локализуются.
"""
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from problems.models import Task, TaskSubitem
from problems.tests import make_invited_teacher, make_teacher

from .builder_rows import RowUrls
from .cart import SESSION_KEY as CART_KEY
from .models import Worksheet, WorksheetItem
from .tests import make_item, make_rubric, make_worksheet

STATIC_JS = Path(settings.BASE_DIR) / 'static' / 'js'


class RowUrlsTests(TestCase):
    """Адреса строк разворачиваются один раз и подставляются строкой —
    результат совпадает с ``reverse`` для каждого адреса."""

    def test_item_and_task_urls_match_reverse(self):
        teacher = make_teacher()
        # id с нулями внутри и на конце: подстановка не должна их трогать
        worksheet = Worksheet.objects.create(pk=100, title='Нули', owner=teacher)
        task = Task.objects.create(pk=2005, text_latex='$1+0$', created_by=teacher)
        item = WorksheetItem.objects.create(pk=1010, worksheet=worksheet, task=task, order=10)
        urls = RowUrls(worksheet.pk)
        row = urls.for_item(item.pk)
        expected = {
            'settings': reverse('worksheet_item_settings', args=[100, 1010]),
            'visibility': reverse('worksheet_item_visibility', args=[100, 1010]),
            'analogs': reverse('worksheet_item_analogs', args=[100, 1010]),
            'move_up': reverse('worksheet_move_item', args=[100, 1010, 'up']),
            'move_down': reverse('worksheet_move_item', args=[100, 1010, 'down']),
            'remove': reverse('worksheet_remove_item', args=[100, 1010]),
            'rubric': reverse('worksheet_set_rubric', args=[100, 1010]),
            'text': reverse('worksheet_edit_text', args=[100, 1010]),
        }
        self.assertEqual(row, expected)
        self.assertEqual(urls.for_task(task.pk), {
            'detail': reverse('task_detail', args=[2005]),
            'manage': reverse('task_manage', args=[2005]),
            'duplicate': reverse('task_duplicate', args=[2005]),
            'clone': reverse('task_clone', args=[2005]),
        })


def items_block(html):
    """HTML списка задач: от #ws-items до плашки «Задач пока нет»."""
    return html.split('id="ws-items"', 1)[1].split('id="ws-empty"', 1)[0]


def row_html(html, item):
    """Разметка одной строки: от её div до следующей строки или конца списка."""
    block = items_block(html)
    start = block.index(f'data-id="{item.pk}"')
    end = block.find('class="ws-item', start + 1)
    return block[start:end if end != -1 else len(block)]


class BuilderRowsMarkupTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1')
        self.worksheet = make_worksheet(self.teacher, n_tasks=3)
        make_rubric(self.worksheet, 'Повторение', order=5)
        self.items = list(self.worksheet.ordered_items())
        self.tasks = [item for item in self.items if item.task_id]
        self.client.login(username='teacher1', password='pass12345')

    def page(self, pk=None):
        response = self.client.get(
            reverse('worksheet_detail', args=[pk or self.worksheet.pk]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_row_actions_and_links(self):
        html = self.page()
        ws = self.worksheet.pk
        first, middle, last = self.tasks
        row = row_html(html, middle)
        self.assertIn('action="%s"' % reverse('worksheet_item_settings', args=[ws, middle.pk]), row)
        self.assertIn('formaction="%s"' % reverse('worksheet_move_item', args=[ws, middle.pk, 'up']), row)
        self.assertIn('formaction="%s"' % reverse('worksheet_move_item', args=[ws, middle.pk, 'down']), row)
        self.assertIn('formaction="%s"' % reverse('worksheet_remove_item', args=[ws, middle.pk]), row)
        self.assertIn('formaction="%s?worksheet=%d&amp;item=%d"' % (
            reverse('task_duplicate', args=[middle.task.pk]), ws, middle.pk), row)
        self.assertIn('data-quick-clone="%s?worksheet=%d&amp;item=%d"' % (
            reverse('task_clone', args=[middle.task.pk]), ws, middle.pk), row)
        self.assertIn('data-manage-url="%s"' % reverse('task_manage', args=[middle.task.pk]), row)
        self.assertIn('href="%s?worksheet=%d&item=%d"' % (
            reverse('task_detail', args=[middle.task.pk]), ws, middle.pk), row)
        self.assertIn('data-vis-url="%s"' % reverse('worksheet_item_visibility', args=[ws, middle.pk]), row)
        # Первая строка листка — без «Выше» (рубрика стоит первой), последняя — без «Ниже»
        self.assertNotIn("/move/up/", row_html(html, self.items[0]))
        self.assertNotIn("/move/down/", row_html(html, last))
        self.assertIn("/move/up/", row_html(html, first))
        # Рубрика: своя форма без адресов задачи
        rubric = row_html(html, self.items[0])
        self.assertIn('action="%s"' % reverse('worksheet_set_rubric', args=[ws, self.items[0].pk]), rubric)
        self.assertNotIn('data-task-id', rubric)

    def test_cart_button_follows_session_cart(self):
        first, second, _ = self.tasks
        session = self.client.session
        session[CART_KEY] = [first.task_id]
        session.save()
        html = self.page()
        in_cart = row_html(html, first)
        self.assertIn('data-in-cart="1"', in_cart)
        self.assertIn('action="%s"' % reverse('cart_remove'), in_cart)
        self.assertIn('name="task_id" value="%d"' % first.task_id, in_cart)
        self.assertIn('name="next" value="%s"' % reverse('worksheet_detail', args=[self.worksheet.pk]), in_cart)
        self.assertIn('class="cart-btn is-in-cart"', in_cart)
        not_in_cart = row_html(html, second)
        self.assertIn('data-in-cart="0"', not_in_cart)
        self.assertIn('action="%s"' % reverse('cart_add'), not_in_cart)
        self.assertIn('class="cart-btn"', not_in_cart)
        # Локальная копия — без кнопки корзины, с бейджем
        local = make_item(self.worksheet, first.task.make_variant(self.teacher))
        row = row_html(self.page(), local)
        self.assertNotIn('data-cart-form', row)
        self.assertIn('badge-local', row)
        self.assertIn('Локальная копия задачи #%d' % first.task_id, row)

    def test_stars_subitems_and_columns(self):
        item = self.tasks[0]
        item.stars_override = 2
        item.columns_override = 3
        item.save()
        task = item.task
        task.columns = 2
        task.save()
        parts = [TaskSubitem.objects.create(task=task, order=i, text_latex=f'$x_{i}$')
                 for i in range(3)]
        html = self.page()
        row = row_html(html, item)
        self.assertIn('data-effective="2"', row)
        self.assertEqual(row.count('class="ws-star on"'), 2)
        self.assertEqual(row.count('class="ws-star"'), 1)
        self.assertIn('data-base="1"', row)
        self.assertIn('name="stars"\n                   value="2"', row)
        self.assertEqual(row.count('name="subitems"'), 3)
        self.assertEqual(row.count('checked>'), 3)  # all_subitems — все отмечены
        self.assertIn('<span class="math-content">$x_0$</span>;', row)
        self.assertIn('<span class="math-content">$x_2$</span>.', row)
        self.assertIn('name="columns" form="settings-%d"' % item.pk, row)
        self.assertIn('value="3"\n                 placeholder="2"', row)
        # Выбраны только два подпункта — третий без галочки
        item.all_subitems = False
        item.save()
        item.subitems.set(parts[:2])
        row = row_html(self.page(), item)
        self.assertEqual(row.count('checked>'), 2)
        self.assertIn('value="%d" form="settings-%d" checked>' % (parts[0].pk, item.pk), row)
        self.assertIn('value="%d" form="settings-%d">' % (parts[2].pk, item.pk), row)

    def test_answers_block_and_flags(self):
        with_answer, without, _ = self.tasks
        without.task.answer_latex = ''
        without.task.save()
        html = self.page()
        row = row_html(html, with_answer)
        self.assertIn('data-has-answer="1"', row)
        self.assertIn('data-no-answer=""', row)
        self.assertIn('<div class="ws-answers" hidden>', row)
        self.assertIn('<strong>Ответ:</strong>', row)
        row = row_html(html, without)
        self.assertIn('data-has-answer=""', row)
        self.assertIn('data-no-answer="1"', row)
        self.assertNotIn('ws-answers', row)

    def test_invited_teacher_sees_base_lock_on_shared_task(self):
        guest = make_invited_teacher('guest1')
        shared = Task.new_for(self.teacher, text_latex='Общая $x$', answer_latex='1')
        own = Task.new_for(guest, text_latex='Своя $y$', answer_latex='2')
        worksheet = Worksheet.objects.create(title='Гость', owner=guest)
        shared_item = WorksheetItem.objects.create(worksheet=worksheet, task=shared, order=10)
        own_item = WorksheetItem.objects.create(worksheet=worksheet, task=own, order=20)
        self.client.logout()
        self.client.login(username='guest1', password='pass12345')
        html = self.page(worksheet.pk)
        self.assertIn('data-base-locked="1"', row_html(html, shared_item))
        self.assertNotIn('data-base-locked', row_html(html, own_item))

    @override_settings(USE_THOUSAND_SEPARATOR=True)
    def test_row_numbers_are_not_localized(self):
        task = Task.objects.create(pk=123456, text_latex='$1$', answer_latex='1', created_by=self.teacher)
        item = WorksheetItem.objects.create(pk=654321, worksheet=self.worksheet, task=task, order=100)
        row = row_html(self.page(), item)
        self.assertIn('data-task-id="123456"', row)
        self.assertIn('>#123456</a>', row)
        self.assertIn('id="settings-654321"', row)
        self.assertIn('data-item="654321"', row)

    def test_queries_do_not_grow_with_rows(self):
        def count(worksheet):
            self.client.get(reverse('worksheet_detail', args=[worksheet.pk]))
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse('worksheet_detail', args=[worksheet.pk]))
            return len(ctx.captured_queries)
        small = make_worksheet(self.teacher, 'Малый', n_tasks=2)
        big = make_worksheet(self.teacher, 'Большой', n_tasks=12)
        for item in big.ordered_items()[:4]:
            TaskSubitem.objects.create(task=item.task, order=1, text_latex='$a$', answer_latex='1')
        self.assertEqual(count(small), count(big))


class LazyMathScriptTests(SimpleTestCase):
    """Договорённости скриптов о ленивом рендере формул (static/js/math.js)."""

    def read(self, name):
        return (STATIC_JS / name).read_text(encoding='utf-8')

    def test_math_js_renders_big_pages_lazily(self):
        src = self.read('math.js')
        self.assertIn('var LAZY_THRESHOLD = 300;', src)
        self.assertIn('new IntersectionObserver(', src)
        self.assertIn('window.EgorMath = {', src)
        for name in ('render:', 'observe:', 'renderAll:', 'isLazy:'):
            self.assertIn(name, src)
        # Маленькие страницы — как раньше: всё сразу
        self.assertIn('blocks.forEach(renderMathContent);', src)
        # Печать — все формулы
        self.assertIn("addEventListener('beforeprint'", src)

    def test_dependents_use_lazy_api(self):
        # Тумблер ответов не рендерит тысячи скрытых формул разом
        self.assertIn('window.EgorMath.observe', self.read('answers-toggle.js'))
        # «Картинкой» дорисовывает свой корень до снимка
        self.assertIn('window.EgorMath.renderAll(source)', self.read('task_png.js'))
        # math.js — первый в склейке app.js: EgorMath нужен остальным
        makefile = (Path(settings.BASE_DIR).parent / 'Makefile').read_text(encoding='utf-8')
        self.assertIn('JS_BASE := math ', makefile)
