from django import template

from ..services import format_span, swap_marks, whole_copies

register = template.Library()


@register.filter
def span(seconds):
    return format_span(seconds)


@register.filter
def plural(number, forms):
    """Русское склонение: {{ n|plural:"раз,раза,раз" }} → форма по числу."""
    one, few, many = forms.split(',')
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


@register.simple_tag
def copied_whole(kind, work):
    """Число копирований условия целиком — для пометки на свёрнутой панели."""
    return whole_copies(kind, [work]).get(work.pk, 0)


@register.simple_tag
def swapped_text(text, swapped):
    return swap_marks(text, swapped)
