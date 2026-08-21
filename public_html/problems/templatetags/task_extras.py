import re

from django import template

from worksheets.latex import subitem_label as _subitem_label

register = template.Library()

_TASKPIC_RE = re.compile(r'\s*\\taskpic(?:\[[^\]]*\])?\{[^}]*\}')


@register.filter
def subitem_label(index0):
    """Метка подпункта по 0-индексу: 0 → «а», 1 → «б», …"""
    return _subitem_label(index0)


@register.filter
def web_text(text):
    """Текст задачи для веб-страниц: прячет маркеры картинок \\taskpic{…}
    (сами картинки показываются отдельным блоком под текстом)."""
    return _TASKPIC_RE.sub('', text or '').strip()
