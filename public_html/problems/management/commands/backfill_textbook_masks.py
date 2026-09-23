import copy

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from problems.models import TextbookImportBatch
from problems.textbook_import import (DEFERRED_MASK_WARNING, TextbookImportError,
                                      _merge_author_fields,
                                      _merge_subitem_author_fields,
                                      fill_draft_answer_masks)


class Command(BaseCommand):
    help = 'Заполняет безопасно выводимые маски ответов в черновиках импорта.'

    def add_arguments(self, parser):
        parser.add_argument('batch_id', type=int)
        parser.add_argument(
            '--apply', action='store_true',
            help='Сохранить рассчитанные маски; без флага работает предпросмотр.')

    def handle(self, *args, **options):
        try:
            batch = TextbookImportBatch.objects.get(pk=options['batch_id'])
        except TextbookImportBatch.DoesNotExist as exc:
            raise CommandError('Партия импорта не найдена.') from exc

        drafts = list(batch.drafts.select_related('imported_task').order_by('pk'))
        changed = []
        targets = generated = unsupported = masks = 0
        for draft in drafts:
            before_parent = draft.answer_mask
            before_subitems = copy.deepcopy(draft.subitems)
            before_warnings = list(draft.warnings)
            if draft.subitems:
                targets += sum(bool(str(item.get('author_answer_latex') or '').strip())
                               for item in draft.subitems)
            else:
                targets += bool(draft.author_answer_latex.strip())

            fill_draft_answer_masks(draft)
            draft.warnings = [w for w in draft.warnings if w != DEFERRED_MASK_WARNING]
            current = ([str(item.get('answer_mask') or '').strip()
                        for item in draft.subitems]
                       if draft.subitems else [draft.answer_mask.strip()])
            masks += sum(bool(value) for value in current)
            if (draft.answer_mask != before_parent
                    or draft.subitems != before_subitems
                    or draft.warnings != before_warnings):
                changed.append(draft)
                if not before_parent and draft.answer_mask:
                    generated += 1
                generated += sum(
                    not str(old.get('answer_mask') or '').strip()
                    and bool(str(new.get('answer_mask') or '').strip())
                    for old, new in zip(before_subitems, draft.subitems))

            if draft.subitems:
                unsupported += sum(
                    bool(str(item.get('author_answer_latex') or '').strip())
                    and not bool(str(item.get('answer_mask') or '').strip())
                    for item in draft.subitems)
            else:
                unsupported += bool(draft.author_answer_latex.strip()) \
                    and not bool(draft.answer_mask.strip())

        transferred = 0
        if options['apply']:
            try:
                with transaction.atomic():
                    if changed:
                        type(drafts[0]).objects.bulk_update(
                            changed, ['answer_mask', 'subitems', 'warnings'], batch_size=500)
                    for draft in drafts:
                        if (draft.status != draft.STATUS_IMPORTED
                                or not draft.imported_task_id):
                            continue
                        task = draft.imported_task
                        if draft.subitems:
                            before = task.subitems.exclude(
                                answer_mask='').count()
                            _merge_subitem_author_fields(task, draft)
                            after = task.subitems.exclude(
                                answer_mask='').count()
                        else:
                            before = bool(task.answer_mask.strip())
                            _merge_author_fields(task, draft)
                            after = bool(task.answer_mask.strip())
                        transferred += after - before
            except TextbookImportError as exc:
                raise CommandError(str(exc)) from exc

        mode = 'сохранено' if options['apply'] else 'предпросмотр'
        self.stdout.write(self.style.SUCCESS(
            f'{mode}: партия {batch.pk}; целей с авторским ответом {targets}; '
            f'масок {masks}; новых {generated}; '
            f'без безопасной маски {unsupported}; '
            f'изменённых задач {len(changed)}; '
            f'перенесено в каталог {transferred}.'))
