"""Выносит прозу из строчных формул в уже загруженных задачах.

Распознанный текст бывает целой формулой: ``$\\text { Даны точки } M(1 ; 1)
\\text { и } N(4 ;-1) .$``. На сайте он идёт шрифтом формулы, не
переносится и даёт отступ первой строки. Команда превращает такие формулы
в обычный текст с формулами (``problems.math_prose.unwrap_math_prose``)
в условиях задач и подпунктов; выключные ``\\[…\\]``/``$$…$$`` не трогает.

По умолчанию только показывает, что изменится; ``--apply`` сохраняет.

    manage.py unwrap_math_prose --source "Авторские листки"
    manage.py unwrap_math_prose --source "Авторские листки" --apply
    manage.py unwrap_math_prose --task 12466 --task 12465 --apply
    manage.py unwrap_math_prose --all          # вся база — только явно
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from problems.math_prose import unwrap_math_prose
from problems.models import Task, TaskSubitem


class Command(BaseCommand):
    help = 'Выносит русский текст из строчных формул в условиях задач и подпунктов'

    def add_arguments(self, parser):
        parser.add_argument('--source', action='append', default=[],
                            help='Только задачи источника (часть названия); можно несколько раз')
        parser.add_argument('--task', action='append', type=int, default=[],
                            help='Только эти задачи (id); можно несколько раз')
        parser.add_argument('--all', action='store_true',
                            help='Все задачи базы, включая созданные учителями вручную')
        parser.add_argument('--apply', action='store_true', help='Сохранить изменения')
        parser.add_argument('--show', type=int, default=10, help='Сколько примеров показать')

    def handle(self, *args, **options):
        # Вся база — только явно: эвристика рассчитана на распознанный текст,
        # задачи, набранные учителями, без нужды не трогаем.
        if not (options['source'] or options['task'] or options['all']):
            raise CommandError('Укажите --source, --task или --all (вся база).')
        tasks = Task.objects.all()
        if options['task']:
            tasks = tasks.filter(pk__in=options['task'])
        if options['source']:
            # Несколько --source — любой из источников («ИЛИ»), как у --task
            match = Q()
            for title in options['source']:
                match |= Q(sources__title__icontains=title)
            tasks = tasks.filter(match)
        tasks = tasks.distinct().order_by('pk')

        task_changes, subitem_changes = [], []
        for task in tasks.only('pk', 'text_latex').iterator():
            fixed = unwrap_math_prose(task.text_latex, display=False)
            if fixed != task.text_latex:
                task_changes.append((task, fixed))
        subitems = TaskSubitem.objects.filter(task__in=tasks).only('pk', 'task_id', 'text_latex')
        for subitem in subitems.iterator():
            fixed = unwrap_math_prose(subitem.text_latex, display=False)
            if fixed != subitem.text_latex:
                subitem_changes.append((subitem, fixed))

        self.stdout.write(f'Задач с изменениями: {len(task_changes)}, '
                          f'подпунктов: {len(subitem_changes)}')
        for obj, fixed in (task_changes + subitem_changes)[:options['show']]:
            label = (f'задача #{obj.pk}' if isinstance(obj, Task)
                     else f'подпункт {obj.pk} задачи #{obj.task_id}')
            self.stdout.write(f'\n{label}\n  было:  {obj.text_latex[:200]}\n  стало: {fixed[:200]}')

        if not options['apply']:
            self.stdout.write('\nНичего не сохранено: запустите с --apply.')
            return
        with transaction.atomic():
            # save(): Task.save пересчитывает text_plain (поиск по задачам)
            for task, fixed in task_changes:
                task.text_latex = fixed
                task.save(update_fields=['text_latex', 'updated_at'])
            for subitem, fixed in subitem_changes:
                subitem.text_latex = fixed
                subitem.save(update_fields=['text_latex'])
        self.stdout.write(self.style.SUCCESS(
            f'\nСохранено: задач {len(task_changes)}, подпунктов {len(subitem_changes)}.'))
