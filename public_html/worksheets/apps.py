from django.apps import AppConfig


class WorksheetsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'worksheets'

    def ready(self):
        from .collection_catalog import connect_collection_catalog_signals
        connect_collection_catalog_signals()
