"""Обложки задачников для полок «Подборок»: страница PDF или картинка →
``Source.cover`` (problems/source_covers.py).

    manage.py source_covers covers.json            # записать (без готовых)
    manage.py source_covers covers.json --force    # переписать готовые
    manage.py source_covers covers.json --dry-run  # только сверить список
    manage.py source_covers covers.json --export DIR

``--export`` ничего не пишет в базу: кладёт JPEG в ``DIR`` и рядом
``covers.json`` с путями к ним. Так обложки переносят на сервер, где
исходных PDF нет: скопировать ``DIR`` и запустить команду с его списком.
"""
import hashlib
import json
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from problems.models import Source
from problems.source_covers import CoverError, find_source, render_cover


class Command(BaseCommand):
    help = 'Обложки задачников из PDF или картинок по списку JSON'

    def add_arguments(self, parser):
        parser.add_argument('mapping',
                            help='JSON: [{"match", "author", "file", "page"}, …]')
        parser.add_argument('--force', action='store_true',
                            help='переписать обложку, если она уже есть')
        parser.add_argument('--dry-run', action='store_true',
                            help='только сверить источники и файлы')
        parser.add_argument('--export', metavar='DIR',
                            help='сохранить JPEG в папку вместо базы')

    def handle(self, *args, mapping, force, dry_run, export, **options):
        mapping_path = Path(mapping)
        try:
            rows = json.loads(mapping_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'{mapping}: {exc}') from exc
        if not isinstance(rows, list):
            raise CommandError(f'{mapping}: нужен список объектов')
        export_dir = Path(export) if export else None
        # --dry-run ничего не пишет и при выгрузке: ни папку, ни covers.json
        if export_dir and not dry_run:
            export_dir.mkdir(parents=True, exist_ok=True)
        exported, done, problems = [], 0, 0
        for row in rows:
            match = str(row.get('match') or '').strip()
            author = str(row.get('author') or '').strip()
            file = Path(str(row.get('file') or ''))
            if not file.is_absolute():
                file = mapping_path.parent / file
            page = int(row.get('page') or 1)
            if not match:
                self.stderr.write(f'— {file.name}: пустой match')
                problems += 1
                continue
            # Выгрузка базу не трогает: источника может ещё не быть локально
            source = label = None
            if export_dir:
                label = f'«{match}»'
            else:
                source, reason = find_source(Source.objects.all(), match, author)
                if not source:
                    self.stderr.write(f'— «{match}»: {reason}')
                    problems += 1
                    continue
                label = f'#{source.pk} {source.title}'
                if source.cover and not force:
                    self.stdout.write(f'= {label}: обложка уже есть')
                    continue
            if not file.is_file():
                self.stderr.write(f'— {label}: нет файла {file}')
                problems += 1
                continue
            if dry_run:
                self.stdout.write(f'· {label} ← {file.name}, стр. {page}')
                continue
            try:
                data = render_cover(file, page)
            except CoverError as exc:
                self.stderr.write(f'— {label}: {exc}')
                problems += 1
                continue
            if export_dir:
                name = f'cover-{len(exported) + 1:02d}.jpg'
                (export_dir / name).write_bytes(data)
                exported.append({'match': match, 'author': author, 'file': name})
            else:
                if source.cover:
                    source.cover.delete(save=False)
                # Хеш в имени — версия для ссылки (worksheets.collection_shelves.cover_url)
                digest = hashlib.sha1(data).hexdigest()[:8]
                source.cover.save(f'source-{source.pk}-{digest}.jpg', ContentFile(data),
                                  save=True)
            done += 1
            self.stdout.write(f'+ {label} ({len(data) // 1024} КБ)')
        if export_dir and not dry_run:
            (export_dir / 'covers.json').write_text(
                json.dumps(exported, ensure_ascii=False, indent=1), encoding='utf-8')
        verb = 'выгружено' if export_dir else 'записано'
        self.stdout.write(f'{verb}: {done}, пропущено с ошибкой: {problems}')
