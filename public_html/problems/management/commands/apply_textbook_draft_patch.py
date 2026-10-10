"""Применяет пакет правок к партии черновиков (по умолчанию — предпросмотр).

    manage.py apply_textbook_draft_patch <партия> <пакет.json> [--apply]

Строка меняется, только если её поля совпадают с прежними значениями
пакета; иначе она пропускается и попадает в отчёт. Перед --apply сохраните
резервную копию: manage.py export_textbook_batches <путь.zip> --batch <партия>.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.models import TextbookImportBatch
from problems.textbook_import import TextbookImportError
from problems.textbook_patches import TextbookPatchError, apply_draft_patch


class Command(BaseCommand):
    help = 'Применяет пакет правок черновиков; без --apply только проверяет.'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)
        parser.add_argument('patch')
        parser.add_argument('--apply', action='store_true',
                            help='Записать правки; без флага — предпросмотр.')

    def handle(self, *args, **options):
        try:
            batch = TextbookImportBatch.objects.get(pk=options['batch_id'])
            patch = json.loads(Path(options['patch']).read_text(encoding='utf-8'))
            report = apply_draft_patch(batch, patch, apply=options['apply'])
        except (TextbookImportBatch.DoesNotExist, OSError, ValueError,
                TextbookPatchError, TextbookImportError) as exc:
            raise CommandError(str(exc))
        mode = 'записано' if options['apply'] else 'предпросмотр, ничего не записано'
        self.stdout.write(
            f'{mode}: задач {len(report["applied"])}, полей {report["fields"]}, '
            f'пропущено {len(report["skipped"])}.')
        for external_id, reason in report['skipped']:
            self.stdout.write(f'  пропущено {external_id}: {reason}')
