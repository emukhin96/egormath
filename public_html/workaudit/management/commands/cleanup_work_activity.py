"""Удаление вспомогательной истории старше 90 дней небольшими пакетами."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from workaudit.models import ActivityEvent, AnswerRevision


class Command(BaseCommand):
    help = 'Удалить события и версии ответов старше 90 дней; текущие ответы сохраняются.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=90)
        for model, field in [(ActivityEvent, 'received_at'), (AnswerRevision, 'created_at')]:
            count = 0
            while True:
                ids = list(model.objects.filter(**{field+'__lt': cutoff}).order_by('pk').values_list('pk', flat=True)[:1000])
                if not ids:
                    break
                deleted, _ = model.objects.filter(pk__in=ids).delete()
                count += deleted
            self.stdout.write(f'{model._meta.verbose_name}: удалено {count}')
