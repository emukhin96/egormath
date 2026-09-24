"""Разовый перенос уже загруженных листков корпуса в «Подборки».

    manage.py authored_to_collections --dry-run   # только показать
    manage.py authored_to_collections             # перенести

Повторяемая: листки, уже лежащие в подборках, пропускаются. Разделы
(по классам, ОГЭ, ЕГЭ, Разное) создаются по мере необходимости; каждая
подборка видна только своему владельцу, пока он её не опубликует.
"""
from django.core.management.base import BaseCommand

from worksheets.authored import (AuthoredError, authored_candidates,
                                 move_to_collections, section_for)


class Command(BaseCommand):
    help = 'Переносит листки с меткой corpus: в подборки «Авторские листки».'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Показать план, ничего не менять')

    def handle(self, *args, **options):
        moved = skipped = 0
        for worksheet in authored_candidates():
            _, section, _ = section_for(worksheet)
            label = f'#{worksheet.pk} «{worksheet.title}» → {section}'
            if options['dry_run']:
                self.stdout.write(label)
                moved += 1
                continue
            try:
                move_to_collections(worksheet, worksheet.owner)
            except AuthoredError as exc:
                self.stdout.write(f'{label}: пропуск — {exc}')
                skipped += 1
                continue
            self.stdout.write(label)
            moved += 1
        verb = 'к переносу' if options['dry_run'] else 'перенесено'
        self.stdout.write(f'Итого {verb}: {moved}, пропущено: {skipped}')
