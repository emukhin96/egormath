"""Какие записи в БД меняют какие живые страницы.

Ключи файлов-версий (см. :mod:`livefile.files`):

- ``assignment:<pk>`` — живая проверка ``/assignments/<pk>/live/`` и
  диалог подробностей;
- ``worksheet:<pk>`` — обзор прогресса листка (и его копия на странице
  листка) и дашборд «Доски»;
- ``student:<user pk>`` — прогресс ученика на ``/assignments/progress/``;
- ``board:<assignment pk>:<task pk>`` — слой учителя на доске ученика
  (меняется только когда учитель рисует, замораживает или удаляет
  страницы, чтобы собственные штрихи ученика не гоняли его за JSON);
- ``run:<pk>`` — прогресс самостоятельной. Исправления живут в другом
  проведении, но показываются в таблице исходного, поэтому трогаем и
  проведение корня попытки.

Записи через ``QuerySet.update()`` сигналов не дают — для них ``touch``
вызывается явно в сервисах (самостоятельные, заморозка страниц доски).
"""
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from assignments.models import (Assignment, Review, Submission, SubmissionCheckAttempt,
                                SubmissionPart, SubmissionPhoto)
from canvas.models import CanvasPage
from independentworks.models import Answer, AnswerCheckAttempt, Attempt, Photo, Run

from . import files

TEACHER_FIELDS = {'teacher_elements', 'teacher_version', 'teacher_updated_at', 'teacher_by', 'locked_at'}


def _assignment(assignment_id):
    row = Assignment.objects.filter(pk=assignment_id).values_list('worksheet_id', 'student_id').first()
    return row or (None, None)


def _submission(submission_id):
    """(assignment_id, task_id, worksheet_id, student_id) или None."""
    return Submission.objects.filter(pk=submission_id).values_list(
        'assignment_id', 'task_id', 'assignment__worksheet_id', 'assignment__student_id').first()


def _touch_submission(submission_id, fallback_assignment_id=None):
    row = _submission(submission_id)
    if row:
        files.touch_assignment(row[0], row[2], row[3])
    elif fallback_assignment_id:
        files.touch_assignment(fallback_assignment_id, *_assignment(fallback_assignment_id))


def _touch_run(run_id, root_id=None):
    files.touch('run', run_id)
    if root_id:
        root_run = Attempt.objects.filter(pk=root_id).values_list('run_id', flat=True).first()
        if root_run and root_run != run_id:
            files.touch('run', root_run)


def _touch_attempt(attempt_id):
    row = Attempt.objects.filter(pk=attempt_id).values_list('run_id', 'root_id').first()
    if row:
        _touch_run(*row)


# --- Назначения листков -----------------------------------------------------

@receiver([post_save, post_delete], sender=Assignment)
def assignment_changed(sender, instance, **kwargs):
    files.touch_assignment(instance.pk, instance.worksheet_id, instance.student_id)


@receiver(m2m_changed, sender=Assignment.hidden_items.through)
def hidden_items_changed(sender, instance, action, **kwargs):
    if action.startswith('post_') and isinstance(instance, Assignment):
        files.touch_assignment(instance.pk, instance.worksheet_id, instance.student_id)


@receiver([post_save, post_delete], sender=Submission)
def submission_changed(sender, instance, **kwargs):
    files.touch_assignment(instance.assignment_id, *_assignment(instance.assignment_id))


@receiver([post_save, post_delete], sender=SubmissionPart)
@receiver([post_save, post_delete], sender=SubmissionCheckAttempt)
@receiver([post_save, post_delete], sender=SubmissionPhoto)
@receiver([post_save, post_delete], sender=Review)
def submission_detail_changed(sender, instance, **kwargs):
    _touch_submission(instance.submission_id)


# --- Доски -------------------------------------------------------------------

def _teacher_side(page, signal, kwargs):
    """Изменение, которое должен увидеть ученик: слой учителя, заморозка, удаление."""
    if signal is post_delete:
        return True
    if kwargs.get('created'):
        return page.created_by_role == CanvasPage.ROLE_TEACHER
    update_fields = kwargs.get('update_fields')
    return update_fields is None or bool(TEACHER_FIELDS & set(update_fields))


@receiver([post_save, post_delete], sender=CanvasPage)
def canvas_page_changed(sender, instance, signal, **kwargs):
    if instance.submission_id:
        row = _submission(instance.submission_id)
        if row:
            files.touch_assignment(row[0], row[2], row[3])
            if _teacher_side(instance, signal, kwargs):
                files.touch('board', row[0], row[1])
    elif instance.answer_id:
        attempt_id = Answer.objects.filter(pk=instance.answer_id).values_list('attempt_id', flat=True).first()
        if attempt_id:
            _touch_attempt(attempt_id)


# --- Самостоятельные ---------------------------------------------------------

@receiver([post_save, post_delete], sender=Run)
def run_changed(sender, instance, **kwargs):
    files.touch('run', instance.pk)


@receiver([post_save, post_delete], sender=Attempt)
def attempt_changed(sender, instance, **kwargs):
    _touch_run(instance.run_id, instance.root_id)


@receiver([post_save, post_delete], sender=Answer)
def answer_changed(sender, instance, **kwargs):
    _touch_attempt(instance.attempt_id)


@receiver([post_save, post_delete], sender=AnswerCheckAttempt)
@receiver([post_save, post_delete], sender=Photo)
def answer_detail_changed(sender, instance, **kwargs):
    attempt_id = Answer.objects.filter(pk=instance.answer_id).values_list('attempt_id', flat=True).first()
    if attempt_id:
        _touch_attempt(attempt_id)
