"""Выгрузка последних партий импорта (Зив / Шестаков) для переноса на прод."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.textbook_transfer import (DEFAULT_PROFILES, TextbookTransferError,
                                        export_batches)


class Command(BaseCommand):
    help = 'Выгружает последние партии ziv/shestakov в каталог (JSON + рисунки)'

    def add_arguments(self, parser):
        parser.add_argument('dest', type=Path)
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
        try:
            payload = export_batches(
                options['dest'], profiles=profiles,
                min_drafts=options['min_drafts'])
        except TextbookTransferError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Выгружено партий: {len(payload["batches"])} → {options["dest"]}'))
