"""Применяет пакет правок к партии черновиков (по умолчанию — предпросмотр).

    manage.py apply_textbook_draft_patch <партия> <пакет.json> [--apply]

Строка меняется, только если её состояние совпадает с исходным в пакете;
иначе она пропускается и попадает в отчёт. Перед --apply сохраните
резервную копию: manage.py export_textbook_batches <путь.zip> --batch <партия>.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.models import TextbookImportBatch
from problems.textbook_patches import apply_draft_patch


class Command(BaseCommand):
    help = 'Применяет пакет правок черновиков; без --apply только проверяет.'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)
        parser.add_argument('patch')
        parser.add_argument('--apply', action='store_true',
                            help='Записать правки; без флага — предпросмотр.')
        parser.add_argument('--allow-other-title', action='store_true',
                            help='Партия на сервере названа иначе, чем исходная.')

    def handle(self, *args, **options):
        try:
            batch = TextbookImportBatch.objects.get(pk=options['batch_id'])
        except TextbookImportBatch.DoesNotExist:
            raise CommandError(f'Партия {options["batch_id"]} не найдена.')
        try:
            patch = json.loads(Path(options['patch']).read_text(encoding='utf-8'))
            report = apply_draft_patch(
                batch, patch, apply=options['apply'],
                allow_other_title=options['allow_other_title'])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'Пакет не применён: {exc}')
        mode = 'записано' if options['apply'] else 'предпросмотр, ничего не записано'
        self.stdout.write(
            f'{mode}: задач {len(report["applied"])}, полей {report["fields"]}, '
            f'уже применено {len(report["already"])}, '
            f'возвращено на проверку {len(report["reset"])}, '
            f'пропущено {len(report["skipped"])}, '
            f'переставлено по порядку книги {report["reordered"]}.')
        for external_id, reason in report['skipped']:
            self.stdout.write(f'  пропущено {external_id}: {reason}')
        for external_id in report['reset']:
            self.stdout.write(f'  снова на проверке {external_id}: была одобрена до правки')
        for external_id, names in report['images']:
            self.stdout.write(f'  нет файлов рисунков {external_id}: {", ".join(names)}')
