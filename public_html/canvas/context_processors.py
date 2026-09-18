from . import services


def canvas(request):
    """Флаг CANVAS_ENABLED для шаблонов: без него панель холста не выводится."""
    return {'canvas_enabled': services.enabled()}
