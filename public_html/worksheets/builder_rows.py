"""Строки конструктора листка: всё, что шаблону нужно от строки, считается
здесь один раз, а не в цикле шаблона (быстродействие 11.2026, второй круг).

На книжном листке 366 строк, и ``worksheets/worksheet_detail.html`` тратил
на них ~0,7 с: 13 ``{% url %}`` на строку, десятки обращений вида
``item.task.effective_…`` через свойства модели, include на каждую мелочь.
Теперь ``rows`` — словари с готовыми адресами, флагами и HTML условия;
шаблон только подставляет их.
"""
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.permissions import can_edit_task
from problems.answer_material import answer_material
from problems.templatetags.task_extras import plural_ru, subitem_tail, web_text

# Рамки «Ответ / Решение» входят в HTML конструктора только у листка не длиннее
# ANSWERS_INLINE_MAX задач (третий круг быстродействия, 11.2026). У длинного
# листка их отдаёт ``worksheet_answers`` (``/worksheets/<pk>/answers/``), когда
# учитель включает тумблер «ответы» (``answers-toggle.js``): на книжном листке
# из 357 задач рамки весили 656 КБ из 2,9 МБ HTML и половину сжатого ответа
# (166 → 86 КБ gzip), а смотрят их редко. Короткий листок — как раньше, всё в
# HTML: без лишнего запроса и без задержки, когда тумблер уже включён.
ANSWERS_INLINE_MAX = 30

# Адреса строк и задач отличаются только одним числом в пути: ``reverse``
# на каждую из 4 771 ссылок страницы стоил 80 мс, поэтому адрес каждого
# вида разворачивается один раз с нулевым id и далее подставляется строкой.
# Сегмент ``/0/`` не совпадёт ни с одним реальным id (автоинкремент с 1).
_PLACEHOLDER = '/0/'
_ITEM_URLS = {
    'settings': ('worksheet_item_settings', ()),
    'visibility': ('worksheet_item_visibility', ()),
    'analogs': ('worksheet_item_analogs', ()),
    'move_up': ('worksheet_move_item', ('up',)),
    'move_down': ('worksheet_move_item', ('down',)),
    'remove': ('worksheet_remove_item', ()),
    'rubric': ('worksheet_set_rubric', ()),
    'text': ('worksheet_edit_text', ()),
}
_TASK_URLS = {
    'detail': 'task_detail',
    'manage': 'task_manage',
    'duplicate': 'task_duplicate',
    'clone': 'task_clone',
}


def _template(name, args):
    url = reverse(name, args=args)
    if url.count(_PLACEHOLDER) != 1:
        raise ValueError(f'{name}: в адресе {url} нет одного места для id')
    return url


class RowUrls:
    """Адреса строки листка и её задачи без ``reverse`` на каждую строку."""

    def __init__(self, worksheet_pk):
        self.item = {key: _template(name, (worksheet_pk, 0, *extra))
                     for key, (name, extra) in _ITEM_URLS.items()}
        self.task = {key: _template(name, (0,)) for key, name in _TASK_URLS.items()}

    def for_item(self, item_pk):
        return {key: url.replace(_PLACEHOLDER, f'/{item_pk}/', 1)
                for key, url in self.item.items()}

    def for_task(self, task_pk):
        return {key: url.replace(_PLACEHOLDER, f'/{task_pk}/', 1)
                for key, url in self.task.items()}


def answers_inline(items):
    """Рамки ответов — прямо в HTML конструктора (короткий листок) или по
    запросу ``worksheet_answers`` (длиннее ``ANSWERS_INLINE_MAX`` задач)."""
    return sum(1 for item in items if item.task_id) <= ANSWERS_INLINE_MAX


def render_answers(items, request=None, only=None):
    """HTML рамок «Ответ / Решение» строк листка: ``{id строки: разметка}``.

    Тот же шаблон и те же данные (``answer_material`` по всем подпунктам
    задачи, ``hide_answers``), что у рамки в HTML конструктора короткого
    листка, — вид не расходится. Строки без ответа и решения пропускаются;
    ``only`` — множество id строк, если нужны не все.
    """
    answers = {}
    for item in items:
        if not item.task_id or (only is not None and item.pk not in only):
            continue
        material = answer_material(item.task)
        if not material:
            continue
        # Без пустых строк от {% load %} и комментария шаблона в начале
        answers[item.pk] = render_to_string('problems/_task_answers.html', {
            'task': item.task, 'material': material,
            'material_ready': True, 'hide_answers': True,
        }, request=request).strip()
    return answers


def decorate_builder_rows(rows, worksheet, user, cart_task_ids, with_answers=True):
    """Дополняет ``rows`` конструктора (``item``, ``number``, ``selected_ids``,
    ``statement``, ``hidden_*``) готовыми значениями для шаблона.

    ``cart_task_ids`` — задачи в корзине учителя (``worksheets.cart.cart_ids``).
    ``with_answers=False`` — рамки ответов (``material``) не собираются: их
    подгрузит ``worksheet_answers`` (см. ``ANSWERS_INLINE_MAX``). Аналоги
    (``task.analog_count``) должны быть уже навешаны: ``attach_analog_counts``
    до вызова.
    """
    urls = RowUrls(worksheet.pk)
    for row in rows:
        item = row['item']
        row['pk'] = item.pk
        row['urls'] = urls.for_item(item.pk)
        if not item.task_id:
            continue
        task = item.task
        subitems = list(task.subitems.all())
        selected = row.get('selected_ids')
        row['urls'].update(urls.for_task(task.pk))
        row['task_pk'] = task.pk
        row['statement_html'] = web_text(row.get('statement', task.text_latex))
        row['subitems'] = [{
            'pk': sub.pk,
            'html': web_text(sub.text_latex),
            'tail': subitem_tail(sub.text_latex, index == len(subitems) - 1),
            'checked': selected is None or sub.pk in selected,
        } for index, sub in enumerate(subitems)]
        row['material'] = answer_material(task, subitems) if with_answers else None
        row['has_answer'] = bool(task.effective_answer_latex
                                 or task.effective_solution_latex
                                 or task.has_subitem_answers)
        row['no_answer'] = task.has_blank_answer
        row['stars'] = item.effective_stars
        row['stars_base'] = task.stars
        row['stars_override'] = ('' if item.stars_override is None
                                 else item.stars_override)
        row['columns_override'] = ('' if item.columns_override is None
                                   else item.columns_override)
        row['columns'] = task.columns
        row['block'] = (f'{task.block.title}, вопрос {task.block_position} из '
                        f'{task.block.size}' if task.block_id else '')
        row['variant_of_id'] = task.variant_of_id
        row['in_cart'] = task.pk in cart_task_ids
        row['full_answer_only'] = task.full_answer_only
        row['base_locked'] = not can_edit_task(user, task)
        row['hidden_any'] = bool(row.get('hidden_links') or row.get('hidden_assignments'))
        count = getattr(task, 'analog_count', 0)
        row['analog_count'] = count
        row['analog_label'] = (f'{count} {plural_ru(count, "аналог,аналога,аналогов")}'
                               if count else '')
    return rows
