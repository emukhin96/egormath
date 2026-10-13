"""Шапка страницы и строка фильтров: ссылки-сегменты с GET-параметрами.

Правила вида — docs/PIPELINE.md, «Шапка страницы и фильтры».
"""
from django import template

register = template.Library()

# Значения, которые фильтр считает одинаковыми: класс 11 — это «10–11».
SEG_ALIASES = {'grade': {'11': '10'}}


def query_url(params, changes):
    """«?…» из текущих GET-параметров с заменами; page сбрасывается.

    Значение None или '' убирает параметр. Пустой результат — «?», чтобы
    ссылка вела на ту же страницу без фильтров.
    """
    query = params.copy()
    query.pop('page', None)
    for key, value in changes.items():
        query.pop(key, None)
        if value is not None and value != '':
            query[key] = str(value)
    encoded = query.urlencode()
    return f'?{encoded}' if encoded else '?'


@register.simple_tag(takes_context=True)
def query_set(context, **changes):
    """``{% query_set grade=8 order=None %}`` → ссылка с текущими фильтрами."""
    return query_url(context['request'].GET, changes)


@register.inclusion_tag('includes/seg_links.html', takes_context=True)
def seg_links(context, param, choices, all_label='Все', label='',
              default='', current=None):
    """Сегменты-ссылки для фильтра с небольшим числом значений.

    choices — пары (значение, подпись); значение '' — «без фильтра».
    all_label добавляет первый сегмент без параметра (None — не добавлять).
    default — какое значение считается выбранным, если параметра нет;
    current — явное текущее значение, если view нормализует параметр сам.
    """
    params = context['request'].GET
    if current is None:
        current = params.get(param, '') or default
    current = str(current)
    current = SEG_ALIASES.get(param, {}).get(current, current)
    items = []
    if all_label:
        items.append({'label': all_label,
                      'url': query_url(params, {param: None}),
                      'active': current == ''})
    for value, text in choices:
        value = '' if value is None else str(value)
        items.append({'label': text,
                      'url': query_url(params, {param: value}),
                      'active': value == current})
    return {'items': items, 'label': label}
