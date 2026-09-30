from django import template

from problems.answer_material import (answer_material as _answer_material,
                                     solution_texts)
from problems.task_images import images_for_group
from problems.textbook_parser import (
    apply_imported_answer, cyrillic_item_label as _cyrillic_item_label,
    normalize_imported_text, order_letter_subitems, strip_heading_dot)
from problems.web_tex import tex_preview_html, tex_to_web_html
from worksheets.latex import subitem_label as _subitem_label

register = template.Library()


@register.inclusion_tag('problems/_task_images.html')
def task_images(task, group='statement'):
    """Картинки задачи: условие, ответы/решения или все."""
    return {'images': images_for_group(task, group)}


@register.simple_tag
def answer_material(task, subitems=None):
    """Рамка «Ответ / Решение»: строки с происхождением (задачник / AI)
    и расхождения между авторским и редакторским вариантами."""
    return _answer_material(task, subitems)


@register.filter
def complete_solutions(owner):
    """Авторское указание и полное решение для редактора и проверки работ."""
    texts = solution_texts(owner)
    if len(texts) > 1:
        # Источник в вебе подписывает шаблон; TeX-заголовок нужен только PDF.
        texts[1] = texts[1].removeprefix(r'\textit{Полное решение от AI.} ')
    return texts


@register.filter
def ordered_subitems(items):
    """Канонический порядок буквенных подпунктов для предпросмотра."""
    return order_letter_subitems(list(items or []))


@register.filter
def subitem_label(index0):
    """Метка подпункта по 0-индексу: 0 → «а», 1 → «б», …"""
    return _subitem_label(index0)


@register.filter
def web_text(text):
    """Текст задачи для веб-страниц: маркеры картинок \\taskpic{…} скрыты,
    форматирующие tex-команды (%, \\\\, \\par, \\annot, tabular…) переведены
    в HTML, формулы остаются для KaTeX."""
    return tex_to_web_html(text)


@register.filter
def web_answer(text):
    """Авторский ответ: голый TeX вроде ``\\{-2;1\\}`` оборачивается для KaTeX."""
    return tex_to_web_html(apply_imported_answer(text))


@register.filter
def cyr_item_label(label):
    """Метка подпункта как в PDF: a → а, b → б."""
    return _cyrillic_item_label(label)


@register.filter
def web_text_preview(text, limit=220):
    """Сокращённое превью условия для списков: обрезка по безопасной
    границе tex (не внутри формулы/команды), затем перевод в HTML."""
    return tex_preview_html(text, int(limit))


@register.filter
def heading_dot(value):
    """Точка в конце названия раздела не нужна даже в старых черновиках."""
    return strip_heading_dot(value)


@register.filter
def without_page(value):
    """Query string или QueryDict без параметра page."""
    if hasattr(value, 'copy') and hasattr(value, 'urlencode'):
        params = value.copy()
        params.pop('page', None)
        return params.urlencode()
    parts = [
        part for part in str(value or '').split('&')
        if part and not part.startswith('page=')]
    return '&'.join(parts)


@register.filter
def page_numbers(page, neighbors=2):
    """Номера страниц с None на месте пропусков: 1 … 4 5 6 … 20."""
    try:
        current = page.number
        last = page.paginator.num_pages
        neighbors = int(neighbors)
    except (AttributeError, TypeError, ValueError):
        return []
    chosen = {1, last}
    chosen.update(
        number for number in range(current - neighbors, current + neighbors + 1)
        if 1 <= number <= last)
    result = []
    previous = None
    for number in sorted(chosen):
        if previous is not None and number > previous + 1:
            result.append(None)
        result.append(number)
        previous = number
    return result


@register.filter
def subitem_tail(text, is_last):
    """Знак после подпункта: «;» между пунктами, «.» после последнего.

    Подпункты-предложения хранятся со своим знаком («Приведите пример.») —
    таким ничего не добавляется.
    """
    text = normalize_imported_text(text or '')
    if text and text[-1] in ';,.!?:':
        return ''
    return '.' if is_last else ';'


@register.filter
def plural_ru(value, forms):
    """Форма слова по числу: ``5|plural_ru:'задача,задачи,задач'`` → «задач»."""
    one, few, many = [form.strip() for form in forms.split(',')]
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return many
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


@register.filter
def sub(value, arg):
    """Вычитание в шаблоне: ``topics|length|sub:limit``."""
    try:
        return int(value) - int(arg)
    except (TypeError, ValueError):
        return ''
