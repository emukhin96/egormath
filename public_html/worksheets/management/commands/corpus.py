"""Обёртка CLI корпуса: inventory / parse / classify из manage.py."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Локальный конвейер авторских листков (inventory/parse/classify).'

    def add_arguments(self, parser):
        parser.add_argument('corpus_cmd',
                            choices=('inventory', 'parse', 'classify'))
        parser.add_argument('--only')
        parser.add_argument('--grade', type=int)
        parser.add_argument('--contains')
        parser.add_argument('--overwrite', action='store_true')

    def handle(self, *args, **options):
        import sys
        from pathlib import Path
        tools = Path(__file__).resolve().parents[4] / 'tools'
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from worksheet_corpus.cli import main
        argv = [options['corpus_cmd']]
        if options.get('only'):
            argv.extend(['--only', options['only']])
        if options.get('grade'):
            argv.extend(['--grade', str(options['grade'])])
        if options.get('contains'):
            argv.extend(['--contains', options['contains']])
        if options.get('overwrite'):
            argv.append('--overwrite')
        code = main(argv)
        if code:
            raise SystemExit(code)
