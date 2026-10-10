"""Пакет правок партии: разница с её исходной выгрузкой.

    manage.py make_textbook_draft_patch <партия> <исходная выгрузка.zip> <пакет.json>
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.models import TextbookImportBatch
from problems.textbook_patches import (TextbookPatchError, build_draft_patch,
                                       current_rows, read_batch_rows)


class Command(BaseCommand):
    help = 'Собирает пакет правок черновиков относительно исходной выгрузки партии.'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)
        parser.add_argument('baseline')
        parser.add_argument('output')

    def handle(self, *args, **options):
        output = Path(options['output'])
        if output.exists():
            raise CommandError(f'Файл уже существует: {output}')
        try:
            batch = TextbookImportBatch.objects.get(pk=options['batch_id'])
            patch = build_draft_patch(
                read_batch_rows(options['baseline']), current_rows(batch),
                source=f'{batch.title} (партия {batch.pk})')
        except (TextbookImportBatch.DoesNotExist, TextbookPatchError) as exc:
            raise CommandError(str(exc))
        output.write_text(json.dumps(patch, ensure_ascii=False, indent=1) + '\n',
                          encoding='utf-8')
        fields = sum(len(row['fields']) for row in patch['drafts'])
        self.stdout.write(f'Пакет: задач {len(patch["drafts"])}, полей {fields} → {output}')
