"""Загрузка партий импорта на прод: темы по code, автор — суперпользователь."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems.textbook_transfer import TextbookTransferError, import_batches


class Command(BaseCommand):
    help = 'Загружает выгрузку export_textbook_batches в текущую базу'

    def add_arguments(self, parser):
        parser.add_argument('src', type=Path)
        parser.add_argument(
            '--username',
            help='Владелец партий; по умолчанию первый суперпользователь')

    def handle(self, *args, **options):
        try:
            created = import_batches(
                options['src'], username=options.get('username'))
        except TextbookTransferError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Загружено партий: {len(created)}'))
