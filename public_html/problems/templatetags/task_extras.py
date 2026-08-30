from django import template

from problems.textbook_parser import normalize_imported_text, order_letter_subitems
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
def subitem_tail(text, is_last):
    """Знак после подпункта: «;» между пунктами, «.» после последнего.

    Подпункты-предложения хранятся со своим знаком («Приведите пример.») —
    таким ничего не добавляется.
    """
    text = normalize_imported_text(text or '')
    if text and text[-1] in ';,.!?:':
        return ''
    return '.' if is_last else ';'
