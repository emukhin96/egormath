"""Разметка задач фасетом CONTENT («Содержание задачи»).

  label_content --seed                    — создать/обновить словарь
  label_content --classify --out f.jsonl  — AI-разметка в файл (база не
      меняется): --ids 1,2,3 | --limit N, --batch 15, --model …
  label_content --from f.jsonl            — показать, что будет записано
  label_content --from f.jsonl --apply    — записать (--replace — снять
      значения CONTENT, которых нет в файле)

По умолчанию ничего не пишет в базу: запись — только с --apply.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from problems import content_tags as ct
from problems.models import Task
from problems.rubricator import seed_content_facet


class Command(BaseCommand):
    help = 'Словарь CONTENT, AI-разметка в файл и запись разметки из файла'

    def add_arguments(self, parser):
        parser.add_argument('--seed', action='store_true')
        parser.add_argument('--classify', action='store_true')
        parser.add_argument('--out')
        parser.add_argument('--ids')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--batch', type=int, default=ct.BATCH_SIZE)
        parser.add_argument('--model')
        parser.add_argument('--from', dest='source')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--replace', action='store_true')

    def handle(self, *args, **opts):
        if not (opts['seed'] or opts['classify'] or opts['source']):
            raise CommandError('Нужен --seed, --classify или --from.')
        if opts['seed']:
            stats = seed_content_facet()
            self.stdout.write(
                f'Словарь: новых {stats["created"]}, удалено {stats["removed"]}'
                + (f', оставлены с задачами: {", ".join(stats["kept"])}'
                   if stats['kept'] else ''))
        if opts['classify']:
            self._classify(opts)
        if opts['source']:
            self._apply(opts)

    def _classify(self, opts):
        if not opts['out']:
            raise CommandError('Для --classify нужен --out.')
        qs = Task.objects.filter(variant_of__isnull=True).order_by('pk')
        if opts['ids']:
            qs = qs.filter(pk__in=[int(x) for x in opts['ids'].split(',')
                                   if x.strip()])
        if opts['limit']:
            qs = qs[:opts['limit']]
        tasks = list(qs.prefetch_related('subitems'))
        call = (lambda prompt: ct.gemini_call(prompt, model=opts['model']))
        written = failed = 0
        with open(opts['out'], 'a', encoding='utf-8') as out:
            for k in range(0, len(tasks), opts['batch']):
                chunk = [ct.task_item(t) for t in tasks[k:k + opts['batch']]]
                try:
                    labels, dropped = ct.classify(chunk, call)
                except ct.ContentLabelError as exc:
                    failed += len(chunk)
                    self.stderr.write(f'Пакет с {chunk[0]["id"]}: {exc}')
                    continue
                for task_id, codes in labels.items():
                    out.write(json.dumps({'id': task_id, 'codes': codes},
                                         ensure_ascii=False) + '\n')
                written += len(labels)
                failed += len(chunk) - len(labels)
                if dropped:
                    self.stderr.write('Не из словаря: ' + ', '.join(dropped))
        self.stdout.write(f'Размечено {written}, без ответа {failed}')

    def _apply(self, opts):
        labels = ct.load_labels(opts['source'])
        if not opts['apply']:
            by_code = ct.content_values_by_code()
            unknown = sorted({c for codes in labels.values() for c in codes
                              if c not in by_code})
            missing = len(set(labels) - set(
                Task.objects.filter(pk__in=list(labels))
                .values_list('pk', flat=True)))
            total = sum(len(c) for c in labels.values())
            self.stdout.write(
                f'Пробный прогон: задач {len(labels)} (нет в базе {missing}), '
                f'значений {total}'
                + (f', неизвестные коды: {", ".join(unknown)}'
                   if unknown else '')
                + '. Запись — с --apply.')
            return
        stats = ct.apply_labels(labels, replace=opts['replace'])
        self.stdout.write(
            f'Записано: задач {stats["tasks"]}, добавлено {stats["added"]}, '
            f'снято {stats["removed"]}, неизвестных кодов {stats["unknown"]}')
