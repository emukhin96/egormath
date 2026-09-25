from django import template

from .. import files

register = template.Library()


@register.simple_tag
def live_file(kind, *ids):
    """URL файла-версии страницы: ``data-live-file="{% live_file 'run' run.pk %}"``."""
    return files.url(kind, *ids)
