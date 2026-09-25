from django.apps import AppConfig


class LivefileConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'livefile'
    verbose_name = 'Файлы-версии живых страниц'

    def ready(self):
        from . import signals  # noqa: F401 — подключение сигналов
