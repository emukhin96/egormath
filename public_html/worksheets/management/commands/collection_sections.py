"""Порядок параграфов в каталожных подборках.

Проверяет, что рубрики «§ N» идут по возрастанию (после импорта задачника
параграф мог попасть не на своё место — так § 3 оказался первым в главе 1
Мерзляка-9), и по запросу переставляет параграфы вместе с их задачами.

    manage.py collection_sections                 # отчёт по всем подборкам
    manage.py collection_sections --source Мерзляк  # только источник
    manage.py collection_sections --fix 1273      # переставить § по номерам
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from worksheets.collection_pages import sections_out_of_order, split_sections
from worksheets.models import Collection


def _ordered_sections(sections):
    """Параграфы по возрастанию номера; безномерные остаются на месте."""
    numbered = sorted(
        (section for section in sections if section.number is not None),
        key=lambda section: section.number)
    result, queue = [], iter(numbered)
    for section in sections:
        result.append(section if section.number is None else next(queue))
    return result


class Command(BaseCommand):
    help = 'Проверить и поправить порядок параграфов «§ N» в подборках'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='',
                            help='Подстрока названия источника')
        parser.add_argument('--fix', type=int, nargs='*', default=[],
                            metavar='PK',
                            help='Переставить параграфы по номерам в этих подборках')

    def handle(self, *args, **options):
        collections = (Collection.objects.select_related('worksheet', 'source')
                       .order_by('source__title', 'pk'))
        if options['source']:
            collections = collections.filter(
                source__title__icontains=options['source'])
        broken = []
        for collection in collections:
            sections = split_sections(collection.worksheet.ordered_items())
            if not any(section.heading is not None for section in sections):
                continue
            wrong = sections_out_of_order(sections)
            numbers = ' '.join(
                str(section.number) if section.number is not None else '—'
                for section in sections)
            mark = 'НЕ ПО ПОРЯДКУ' if wrong else 'ok'
            self.stdout.write(
                f'{collection.pk:>6}  {collection.source.title} · '
                f'{collection.worksheet.title}: § {numbers}  {mark}')
            if wrong:
                broken.append(collection.pk)
        for pk in options['fix']:
            self._fix(pk)
        if broken and not options['fix']:
            self.stdout.write(self.style.WARNING(
                'Поправить: manage.py collection_sections --fix '
                + ' '.join(map(str, broken))))

    @transaction.atomic
    def _fix(self, pk):
        try:
            collection = Collection.objects.select_related('worksheet').get(pk=pk)
        except Collection.DoesNotExist:
            raise CommandError(f'Подборки {pk} нет')
        items = list(collection.worksheet.ordered_items())
        sections = split_sections(items)
        ordered = _ordered_sections(sections)
        if ordered == sections:
            self.stdout.write(f'{pk}: параграфы уже по порядку')
            return
        order = 10
        for section in ordered:
            for item in ([section.heading] if section.heading is not None else []) + section.items:
                if item.order != order:
                    item.order = order
                    item.save(update_fields=['order'])
                order += 10
        self.stdout.write(self.style.SUCCESS(
            f'{pk}: параграфы переставлены — § '
            + ' '.join(str(s.number) if s.number is not None else '—'
                       for s in ordered)))
