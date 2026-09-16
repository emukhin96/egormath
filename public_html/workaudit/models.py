"""Наблюдения браузера и снимки успешно сохранённых ответов."""
from django.db import models
from django.db.models import Q


class ActivityEvent(models.Model):
    assignment = models.ForeignKey('assignments.Assignment', null=True, blank=True, on_delete=models.CASCADE)
    attempt = models.ForeignKey('independentworks.Attempt', null=True, blank=True, on_delete=models.CASCADE)
    event_id = models.UUIDField(unique=True)
    page_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=[
        ('hidden', 'Страница скрыта'), ('visible', 'Возврат на страницу'),
        ('copy', 'Копирование условия'), ('paste', 'Вставка ответа'), ('drop', 'Перенос текста')])
    blocked = models.BooleanField(default=False)
    client_at = models.DateTimeField()
    elapsed_ms = models.PositiveBigIntegerField()
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.CheckConstraint(name='audit_event_one_work', check=(
            Q(assignment__isnull=False, attempt__isnull=True) |
            Q(assignment__isnull=True, attempt__isnull=False)))]
        indexes = [models.Index(fields=['assignment', 'received_at']), models.Index(fields=['attempt', 'received_at'])]


class AnswerRevision(models.Model):
    submission = models.ForeignKey('assignments.Submission', null=True, blank=True, on_delete=models.CASCADE)
    part = models.ForeignKey('assignments.SubmissionPart', null=True, blank=True, on_delete=models.CASCADE)
    answer = models.ForeignKey('independentworks.Answer', null=True, blank=True, on_delete=models.CASCADE)
    snapshot = models.JSONField()
    initial = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.CheckConstraint(name='audit_revision_one_answer', check=(
            Q(submission__isnull=False, part__isnull=True, answer__isnull=True) |
            Q(submission__isnull=True, part__isnull=False, answer__isnull=True) |
            Q(submission__isnull=True, part__isnull=True, answer__isnull=False)))]
        indexes = [models.Index(fields=[field, 'created_at']) for field in ('submission', 'part', 'answer')]
