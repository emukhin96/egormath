"""Загрузка партий импорта на прод: темы по code, автор — суперпользователь."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.textbook_transfer import TextbookTransferError, import_batches


class Command(BaseCommand):
    help = 'Загружает выгрузку export_textbook_batches в текущую базу'

    def add_arguments(self, parser):
        parser.add_argument('src', type=Path)
        parser.add_argument('--check-only', action='store_true', help='Проверить без записи')
        parser.add_argument(
            '--username',
            help='Владелец партий; по умолчанию первый суперпользователь')

    def handle(self, *args, **options):
        try:
            created = import_batches(
                options['src'], username=options.get('username'), check_only=options['check_only'])
        except TextbookTransferError as exc:
            raise CommandError(str(exc)) from exc
        if options['check_only']:
            self.stdout.write('Пакет и справочники проверены; записей не создано.')
            return
        for batch in created:
            self.stdout.write(json.dumps(dict(batch_id=batch.pk, drafts=batch.drafts.count(),
                assets=batch.assets.count(), path=f'/problems/imports/{batch.pk}/',
                transfer_key=batch.transfer_key), ensure_ascii=False))
