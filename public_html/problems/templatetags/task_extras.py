from django import template

from problems.textbook_parser import (
    normalize_imported_text, order_letter_subitems, strip_heading_dot)
from problems.web_tex import tex_preview_html, tex_to_web_html
from worksheets.latex import subitem_label as _subitem_label

register = template.Library()


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
