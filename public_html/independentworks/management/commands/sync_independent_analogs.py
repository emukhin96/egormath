from django.core.management.base import BaseCommand
from independentworks.analogs import sync_families


class Command(BaseCommand):
    help = 'Заполнить связи аналогов ФИПИ и парных вариантов Зива'

    def handle(self, *args, **options):
        self.stdout.write(f'Обработано семейств: {sync_families()}')
