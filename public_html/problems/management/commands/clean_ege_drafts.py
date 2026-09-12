"""Повторяемая локальная очистка черновиков с журналом до/после."""
import copy
import hashlib
import json
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from problems.ege_cleanup import (clean_ege_rows, PDF_SHA256, PDF_FIGURE_STEM,
                                  PDF_FIGURE_PAGE, PDF_FIGURE_CLIP)
from problems.models import TextbookImportBatch, TextbookImportAsset

FIELDS = ['text_latex', 'subitems', 'author_answer_latex', 'author_solution_latex', 'images']


class Command(BaseCommand):
    help = 'Очистить оформление партии ЕГЭ; запись только с --commit'

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=int, required=True)
        parser.add_argument('--report', type=Path, required=True)
        parser.add_argument('--pdf', type=Path)
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        with transaction.atomic():
            batch = TextbookImportBatch.objects.select_for_update().get(pk=options['batch'])
            if batch.profile != 'ostromogilsky_ege':
                raise CommandError('Нужна партия ЕГЭ.')
            drafts = list(batch.drafts.select_for_update().order_by('pk'))
            if any(d.imported_task_id for d in drafts):
                raise CommandError('Партия уже содержит задачи каталога; нужна отдельная сверка.')
            before = [dict(id=d.pk, external_id=d.external_id,
                           **{f: getattr(d, f) for f in FIELDS}) for d in drafts]
            after = copy.deepcopy(before)
            changes = clean_ege_rows(after)
            needs_image = (any(PDF_FIGURE_STEM in r['images'] for r in after)
                           and not batch.assets.filter(stem=PDF_FIGURE_STEM).exists())
            image = None
            if needs_image:
                pdf = options['pdf']
                if not pdf or hashlib.sha256(pdf.read_bytes()).hexdigest() != PDF_SHA256:
                    raise CommandError('Для восстановления рисунка нужен PDF с ожидаемой SHA-256.')
                import fitz
                with fitz.open(pdf) as doc:
                    image = doc[PDF_FIGURE_PAGE - 1].get_pixmap(
                        matrix=fitz.Matrix(3, 3), clip=fitz.Rect(PDF_FIGURE_CLIP)).tobytes('png')
            report = options['report']
            report.parent.mkdir(parents=True, exist_ok=True)
            # Уникальное имя предотвращает потерю предыдущего журнала исправлений.
            if report.exists():
                raise CommandError('Журнал уже существует; укажите новое имя --report.')
            report.write_text(json.dumps(dict(batch=batch.pk, commit_requested=options['commit'],
                changed_tasks=len(changes), restored_image=bool(image), changes=changes,
                before=before, after=after), ensure_ascii=False, indent=2))
            if options['commit']:
                changed = []
                for draft, old, new in zip(drafts, before, after):
                    if old != new:
                        for field in FIELDS:
                            setattr(draft, field, new[field])
                        changed.append(draft)
                if changed:
                    batch.drafts.model.objects.bulk_update(changed, FIELDS)
                if image:
                    asset = TextbookImportAsset(batch=batch, stem=PDF_FIGURE_STEM,
                                                original_name=PDF_FIGURE_STEM + '.png')
                    asset.file.save(asset.original_name, ContentFile(image), save=True)
            self.stdout.write(f'changed={len(changes)}; image={bool(image)}; commit={options["commit"]}')
