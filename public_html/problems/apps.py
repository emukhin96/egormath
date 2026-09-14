from django.apps import AppConfig


class ProblemsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'problems'

    def ready(self):
        from .rubricator import (connect_exam_parent_signal,
                                 connect_taxonomy_cache_signals)
        connect_exam_parent_signal()
        connect_taxonomy_cache_signals()
