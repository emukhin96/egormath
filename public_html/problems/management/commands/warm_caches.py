"""Прогрев кэшей, которым нужна база: справочник рубрикатора и дерево
подборок (``taxonomy``), значения масок открытых самостоятельных
(``numeric``) — ``core.warmup.warm_worker``.

Воркеры gunicorn делают то же сами при старте (``post_worker_init``), но
``deploy.sh`` сбрасывает кэш каталога уже после старта контейнера — иначе
старые воркеры успели бы записать его заново. Поэтому после сброса кэш
собирается этой командой, пока сайт уже отвечает: первый посетитель после
выкладки получает тёплые справочники (ревью PR #345).
"""
import time

from django.core.management.base import BaseCommand

from core.warmup import warm_worker


class Command(BaseCommand):
    help = 'Прогреть кэши справочников и масок открытых самостоятельных'

    def handle(self, *args, **options):
        started = time.perf_counter()
        masks = warm_worker()
        self.stdout.write(f'кэши прогреты за {time.perf_counter() - started:.2f} с, масок: {masks}')
