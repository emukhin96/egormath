"""Локальная загрузка пакета ЕГЭ с защитой от повторов и потери правок."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from problems.models import ExamItem, TextbookImportBatch
from problems.textbook_import import create_batch_from_bundle, attach_image_archive


class Command(BaseCommand):
    help = 'Проверить пакет ЕГЭ; --commit создаёт только черновики, без каталога'

    def add_arguments(self, parser):
        parser.add_argument('bundle', type=Path)
        parser.add_argument('--username', default='egor')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        path = options['bundle']
        payload = json.loads(path.read_text())
        if payload.get('profile') != 'ostromogilsky_ege':
            raise CommandError('Нужен профиль ostromogilsky_ege.')
        rows = payload.get('tasks') or []
        ids = [row['external_id'] for row in rows]
        if not rows or len(ids) != len(set(ids)):
            raise CommandError('Пустой пакет или повторяющиеся номера.')
        codes = {code for row in rows for code in row.get('exam_item_codes', [])}
        missing_codes = codes - set(ExamItem.objects.filter(code__in=codes).values_list('code', flat=True))
        if missing_codes:
            raise CommandError('Отсутствуют метки: ' + ', '.join(sorted(missing_codes)))
        image_dir = path.parent / 'images'
        files = []
        for stem in sorted({stem for row in rows for stem in row.get('images', [])}):
            matches = [p for p in image_dir.glob(stem + '.*') if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.pdf'}]
            if len(matches) != 1:
                raise CommandError(f'Рисунок {stem}: найдено файлов {len(matches)}.')
            files.append(matches[0])
        file_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        fingerprint = hashlib.sha256(json.dumps(
            [payload, file_hashes], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        # Идентичный пакет никогда не переписывает отредактированные черновики.
        existing = TextbookImportBatch.objects.filter(
            profile='ostromogilsky_ege', diagnostics__bundle_fingerprint=fingerprint).first()
        if existing:
            self.stdout.write(f'unchanged: batch={existing.pk}; черновики сохранены')
            return
        source_sha = payload.get('source', {}).get('tasks_sha256')
        if source_sha and TextbookImportBatch.objects.filter(
                profile='ostromogilsky_ege', diagnostics__source_sha256=source_sha).exists():
            raise CommandError('Для этого исходника уже есть другая версия партии. '
                               'Нужна сверка изменений, автоматическая перезапись запрещена.')
        if not options['commit']:
            self.stdout.write(f'Проверено: {len(rows)} задач, {len(files)} рисунков; записей не создано')
            return
        user = get_user_model().objects.filter(username=options['username'], is_superuser=True).first()
        if not user:
            raise CommandError('Нужен существующий суперпользователь --username.')
        payload.setdefault('diagnostics', {}).update(
            bundle_fingerprint=fingerprint, source_sha256=source_sha)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
            for image in files:
                out.write(image, image.name)
        archive.seek(0)
        with transaction.atomic():
            batch = create_batch_from_bundle(
                payload, user=user, title='Открытый банк ЕГЭ — 2027',
                source_title='Открытый банк задач ФИПИ. ЕГЭ по профильной математике',
                source_author='Остромогильский А. Д.', source_year=2026)
            if files:
                attach_image_archive(batch, archive)
        self.stdout.write(f'created: batch={batch.pk}; /problems/imports/{batch.pk}/')
