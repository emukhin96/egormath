from django.core.management.base import BaseCommand
import json
from django.core.management.base import CommandError
from problems.models import Source, TaskSource
from worksheets.models import Collection
from independentworks.analogs import sync_families


class Command(BaseCommand):
    help = 'Заполнить связи аналогов ФИПИ и парных вариантов Зива'

    def add_arguments(self, parser):
        parser.add_argument('--source', type=int, help='ID источника в этой базе')
        parser.add_argument('--dry-run', action='store_true', help='Только отчёт, без записи')
        parser.add_argument('--json', action='store_true', help='Отчёт JSON')

    def handle(self, *args, **options):
        source_id = options['source']
        source = Source.objects.filter(pk=source_id).first() if source_id is not None else None
        if source_id is not None and source is None:
            raise CommandError('Источник не найден в этой базе.')
        report = sync_families(dry_run=options['dry_run'], report=True, source_id=source_id)
        if source:
            report['source'] = {'id': source.pk, 'title': source.title,
                'task_references': TaskSource.objects.filter(source=source).count(),
                'collections': Collection.objects.filter(source=source).count()}

        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if source:
            self.stdout.write(f"Источник #{source.pk}: {source.title}; записей задач: {report['source']['task_references']}; подборок: {report['source']['collections']}")
            if not report['source']['task_references'] and not report['source']['collections']:
                self.stdout.write('В этой базе нет импортированных задач и подборок источника. Связи не заполнены.')
        self.stdout.write(('Предварительный отчёт. ' if options['dry_run'] else '') +
            f"Семейств: {report['families']}; новых: {report['created']}; новых участников: {report['members_added']}; уточнённых ключей: {report['keys_updated']}")
        for category, label in [('incomplete', 'Неполные пары'), ('ambiguous', 'Неоднозначности')]:
            self.stdout.write(f'{label}: {len(report[category])}')
            for message in report[category]:
                self.stdout.write('  ' + message)
