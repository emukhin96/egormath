"""Сброс файловых кэшей каталога: справочники рубрикатора и дерево подборок
(``taxonomy``), счётчики разделов, классов и источников (``catalog``).

Обычно они сбрасываются сигналами сами. Команда нужна после записей мимо
ORM: заливки дампа (``deploy/vps/import-db.sh`` вызывает её сам), скриптов,
пишущих прямо в MySQL, ручных правок в базе.
"""
from django.core.cache import caches
from django.core.management.base import BaseCommand

ALIASES = ('taxonomy', 'catalog')


class Command(BaseCommand):
    help = 'Сбросить файловые кэши каталога задач и подборок (taxonomy, catalog)'

    def handle(self, *args, **options):
        for alias in ALIASES:
            caches[alias].clear()
            self.stdout.write(f'{alias}: сброшен')
