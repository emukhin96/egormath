"""Сводка по холстам: сколько страниц, какого размера, где растёт.

Запускать вручную (cron на проде сознательно не используется):
    manage.py canvas_stats
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import Count

from canvas.models import CanvasPage


class Command(BaseCommand):
    help = 'Число страниц холста, средний и максимальный размер JSON, доля задач с холстом'

    def handle(self, *args, **options):
        pages = CanvasPage.objects.all().only(
            'student_elements', 'teacher_elements', 'locked_at', 'created_by_role', 'submission_id')
        total = 0
        sizes = []
        empty = 0
        locked = 0
        by_teacher = 0
        for page in pages.iterator(chunk_size=200):
            total += 1
            size = (len(json.dumps(page.student_elements, separators=(',', ':')))
                    + len(json.dumps(page.teacher_elements, separators=(',', ':'))))
            sizes.append(size)
            if page.is_empty:
                empty += 1
            if page.is_locked:
                locked += 1
            if page.created_by_role == CanvasPage.ROLE_TEACHER:
                by_teacher += 1
        tasks_with_canvas = (CanvasPage.objects.filter(submission__isnull=False)
                             .values('submission_id').annotate(n=Count('pk')).count())
        from assignments.models import Submission
        submissions = Submission.objects.count()
        self.stdout.write(f'Страниц: {total} (пустых {empty}, замороженных {locked}, учительских {by_teacher})')
        if sizes:
            sizes.sort()
            self.stdout.write(
                f'Размер JSON: средний {sum(sizes) // len(sizes) / 1024:.1f} КБ, '
                f'медиана {sizes[len(sizes) // 2] / 1024:.1f} КБ, максимум {sizes[-1] / 1024:.1f} КБ, '
                f'всего {sum(sizes) / 1024 / 1024:.2f} МБ')
        share = tasks_with_canvas / submissions * 100 if submissions else 0
        self.stdout.write(f'Ответов с холстом: {tasks_with_canvas} из {submissions} ({share:.0f}%)')
