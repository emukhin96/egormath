"""Выгрузка последних партий импорта (Зив / Шестаков) для переноса на прод."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.models import TextbookImportBatch
from problems.textbook_transfer import (DEFAULT_PROFILES, TextbookTransferError,
                                        export_batches)


class Command(BaseCommand):
    help = 'Выгружает черновики и рисунки в ZIP или каталог'

    def add_arguments(self, parser):
        parser.add_argument('dest', type=Path)
        parser.add_argument('--batch', type=int, action='append', help='Точный ID партии; можно повторить')
        parser.add_argument(
            '--profiles', default=','.join(DEFAULT_PROFILES),
            help='Список профилей через запятую')
        parser.add_argument(
            '--min-drafts', type=int, default=10,
            help='Игнорировать крошечные тестовые партии')

    def handle(self, *args, **options):
        profiles = tuple(
            item.strip() for item in options['profiles'].split(',')
            if item.strip())
        batches = None
        if options['batch']:
            batches = list(TextbookImportBatch.objects.filter(pk__in=options['batch']).order_by('pk'))
            if {b.pk for b in batches} != set(options['batch']):
                raise CommandError('Не найдены указанные партии.')
        try:
            payload = export_batches(
                options['dest'], profiles=profiles, batches=batches,
                min_drafts=options['min_drafts'])
        except TextbookTransferError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Выгружено партий: {len(payload["batches"])} → {options["dest"]}'))
