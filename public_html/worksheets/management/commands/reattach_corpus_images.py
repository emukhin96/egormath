"""Догрузка рисунков корпуса к уже импортированным листкам."""

from django.core.management.base import BaseCommand, CommandError

from worksheets.corpus import list_drafts, reattach_draft_images


class Command(BaseCommand):
    help = (
        'Копирует рисунки из var/worksheets-import/assets в задачи '
        'уже загруженных листков корпуса. Нужно, если импорт смотрел '
        'на абсолютные пути другой машины.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--key',
            help='id черновика, например «8 класс/matvert8-geom-prop_otr»')
        parser.add_argument(
            '--all', action='store_true',
            help='все черновики со статусом imported')

    def handle(self, *args, **options):
        key = options.get('key')
        drafts = list_drafts()
        if key:
            drafts = [d for d in drafts if d.get('id') == key]
            if not drafts:
                raise CommandError(f'Черновик не найден: {key}')
        elif options.get('all'):
            drafts = [d for d in drafts if d.get('status') == 'imported']
        else:
            raise CommandError('Укажите --key или --all')

        total = 0
        for draft in drafts:
            worksheet, info = reattach_draft_images(draft)
            if info.get('skipped') or worksheet is None:
                if key:
                    raise CommandError(
                        f'Листок в каталоге не найден: {draft["id"]}')
                continue
            attached = info.get('attached') or 0
            total += attached
            self.stdout.write(f'{draft["id"]}: догружено {attached}')
            missing = info.get('missing') or []
            if missing:
                self.stderr.write(self.style.WARNING(
                    '  нет файлов: ' + ', '.join(missing)))
        self.stdout.write(self.style.SUCCESS(f'Итого догружено: {total}'))
