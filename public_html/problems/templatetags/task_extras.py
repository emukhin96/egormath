from django import template

from problems.web_tex import tex_to_web_html
from worksheets.latex import subitem_label as _subitem_label

register = template.Library()


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
