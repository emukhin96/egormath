from django.core.management.base import BaseCommand
import json
from independentworks.analogs import sync_families


class Command(BaseCommand):
    help = 'Заполнить связи аналогов ФИПИ и парных вариантов Зива'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Только отчёт, без записи')
        parser.add_argument('--json', action='store_true', help='Отчёт JSON')

    def handle(self, *args, **options):
        report = sync_families(dry_run=options['dry_run'], report=True)
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return
        self.stdout.write(('Предварительный отчёт. ' if options['dry_run'] else '') +
            f"Семейств: {report['families']}; новых: {report['created']}; новых участников: {report['members_added']}; уточнённых ключей: {report['keys_updated']}")
        for category, label in [('incomplete', 'Неполные пары'), ('ambiguous', 'Неоднозначности')]:
            self.stdout.write(f'{label}: {len(report[category])}')
            for message in report[category]:
                self.stdout.write('  ' + message)
