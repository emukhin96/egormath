"""Разметка задач фасетом CONTENT («Содержание задачи»).

Размечают агенты Claude Code по файлам-пакетам (без внешних API):

  label_content --seed                      — создать/обновить словарь
  label_content --make-batches DIR          — пакеты для агентов:
      DIR/batch_001.md … и DIR/manifest.json; --ids 1,2,3 | --limit N,
      --size 30 (задач в пакете), --shared (только общие задачи)
  label_content --from DIR|файл             — показать, что будет записано
  label_content --from DIR|файл --apply     — записать (--replace — снять
      значения CONTENT, которых нет в ответе)
      --hashes FILE — {id: отпечаток текста}: задачи, чей текст изменился
      после разметки, пропускаются (--make-batches пишет DIR/hashes.json,
      --from DIR берёт его сам; без отпечатков — предупреждение); --backup FILE — до записи сохранить
      прежние значения CONTENT этих задач (файл отката)
  label_content --drop-param-tag [--apply]  — снять тег «задача с
      параметром» у задач со значением группы «Параметр» (решение 07.11)

Ответ агента — DIR/batch_001.answer.json: {"items": [{"id", "codes"}]}.
Файлом разметки может быть и {"<id>": [коды]} или JSONL {"id", "codes"}.
По умолчанию ничего не пишет в базу: запись — только с --apply.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from problems import content_tags as ct
from problems.models import Task
from problems.rubricator import seed_content_facet


class Command(BaseCommand):
    help = 'Словарь CONTENT, пакеты для агентов и запись разметки из ответов'

    def add_arguments(self, parser):
        parser.add_argument('--seed', action='store_true')
        parser.add_argument('--make-batches', dest='batches')
        parser.add_argument('--ids')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--size', type=int, default=ct.BATCH_SIZE)
        parser.add_argument('--shared', action='store_true')
        parser.add_argument('--from', dest='source')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--replace', action='store_true')
        parser.add_argument('--hashes')
        parser.add_argument('--backup')
        parser.add_argument('--drop-param-tag', action='store_true')

    def handle(self, *args, **opts):
        if not (opts['seed'] or opts['batches'] or opts['source']
                or opts['drop_param_tag']):
            raise CommandError(
                'Нужен --seed, --make-batches, --from или --drop-param-tag.')
        if opts['seed']:
            stats = seed_content_facet()
            self.stdout.write(
                f'Словарь: новых {stats["created"]}, удалено {stats["removed"]}'
                + (f', оставлены с задачами: {", ".join(stats["kept"])}'
                   if stats['kept'] else ''))
        if opts['batches']:
            self._make_batches(opts)
        if opts['source']:
            self._apply(opts)
        if opts['drop_param_tag']:
            self._drop_param_tag(opts)

    def _make_batches(self, opts):
        out = Path(opts['batches'])
        out.mkdir(parents=True, exist_ok=True)
        qs = Task.objects.filter(variant_of__isnull=True).order_by('pk')
        if opts['shared']:
            qs = qs.filter(is_shared=True)
        if opts['ids']:
            qs = qs.filter(pk__in=[int(x) for x in opts['ids'].split(',')
                                   if x.strip()])
        if opts['limit']:
            qs = qs[:opts['limit']]
        tasks = list(qs.prefetch_related('subitems'))
        size = max(1, opts['size'])
        manifest = {}
        for n, k in enumerate(range(0, len(tasks), size), start=1):
            chunk = [ct.task_item(t) for t in tasks[k:k + size]]
            name = f'batch_{n:03d}.md'
            ct.write_batch(chunk, out / name)
            manifest[name] = [item['id'] for item in chunk]
        (out / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        # Отпечатки текста на момент нарезки: --from DIR берёт их сам и
        # пропускает задачи, чьё условие успели изменить.
        (out / ct.HASHES_NAME).write_text(json.dumps(
            {str(t.pk): ct.task_text_hash(t) for t in tasks}), encoding='utf-8')
        self.stdout.write(f'Пакетов {len(manifest)}, задач {len(tasks)}: {out}')

    def _labels_from_dir(self, folder):
        manifest = json.loads((folder / 'manifest.json').read_text('utf-8'))
        labels, dropped, missing = {}, [], []
        for name, ids in manifest.items():
            answer = (folder / name).with_suffix('.answer.json')
            if not answer.exists():
                missing.append(name)
                continue
            try:
                got, bad = ct.read_answer(answer, ids)
            except ct.ContentLabelError as exc:
                self.stderr.write(f'{answer.name}: {exc}')
                missing.append(name)
                continue
            labels.update(got)
            dropped += bad
            lost = len(ids) - len(got)
            if lost:
                self.stderr.write(f'{answer.name}: без ответа задач {lost}')
        if missing:
            self.stderr.write('Нет ответа на пакеты: ' + ', '.join(missing))
        if dropped:
            self.stderr.write('Не из словаря (отброшены): '
                              + ', '.join(sorted(set(dropped))))
        return labels

    def _apply(self, opts):
        source = Path(opts['source'])
        labels = (self._labels_from_dir(source) if source.is_dir()
                  else ct.load_labels(source))
        hashes_path = opts['hashes']
        if not hashes_path and source.is_dir() and (
                source / ct.HASHES_NAME).exists():
            hashes_path = source / ct.HASHES_NAME
        if not hashes_path:
            self.stderr.write('Без отпечатков текста (--hashes): задачи, '
                              'изменённые после разметки, не отсеиваются.')
        if hashes_path:
            hashes = json.loads(Path(hashes_path).read_text('utf-8'))
            stale = ct.stale_tasks(labels, hashes)
            if stale:
                self.stdout.write(
                    f'Текст изменился после разметки, пропущено задач '
                    f'{len(stale)}: ' + ', '.join(map(str, sorted(stale)[:30]))
                    + (' …' if len(stale) > 30 else ''))
            labels = {k: v for k, v in labels.items() if k not in stale}
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
        if opts['backup']:
            Path(opts['backup']).write_text(json.dumps(
                ct.current_content(labels), ensure_ascii=False), 'utf-8')
            self.stdout.write(f'Откат: {opts["backup"]}')
        stats = ct.apply_labels(labels, replace=opts['replace'])
        self.stdout.write(
            f'Записано: задач {stats["tasks"]}, добавлено {stats["added"]}, '
            f'снято {stats["removed"]}, неизвестных кодов {stats["unknown"]}')

    def _drop_param_tag(self, opts):
        if not opts['apply']:
            from problems.models import Tag
            tag = Tag.objects.filter(name__iexact=ct.PARAM_TAG_NAME).first()
            n = tag.tasks.count() if tag else 0
            self.stdout.write(f'Тег «{ct.PARAM_TAG_NAME}» у задач: {n}. '
                              'Снятие — с --apply.')
            return
        plan = ct.param_tag_plan()
        if opts['backup']:
            # Список — до снятия: не записался файл, не трогаем и базу.
            Path(opts['backup']).write_text(json.dumps(
                {'tag': ct.PARAM_TAG_NAME, 'removed_from': plan['removed']}),
                'utf-8')
            self.stdout.write(f'Откат: {opts["backup"]}')
        stats = ct.drop_param_tag(plan)
        self.stdout.write(
            f'Тег снят у {len(stats["removed"])} задач; оставлен у '
            f'{len(stats["kept"])} без значения «Параметр»: '
            + ', '.join(map(str, stats['kept'][:50])))
