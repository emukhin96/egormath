"""Старые ответы остаются читаемыми после удаления настроек задачи."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyAnswerMigrationTests(TransactionTestCase):
    def test_preserves_old_answers_and_checks(self):
        executor = MigrationExecutor(connection)
        current = executor.loader.graph.leaf_nodes()
        before = [('problems', '0019_exam_line_items'),
                  ('assignments', '0008_submissioncheckattempt')]
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            user = apps.get_model('auth', 'User').objects.create(username='history')
            worksheet = apps.get_model('worksheets', 'Worksheet').objects.create(
                title='История', owner_id=user.pk)
            assignment = apps.get_model('assignments', 'Assignment').objects.create(
                worksheet_id=worksheet.pk, student_id=user.pk)
            Task = apps.get_model('problems', 'Task')
            Submission = apps.get_model('assignments', 'Submission')
            number = Task.objects.create(text_latex='Число', answer_type='number')
            numeric = Submission.objects.create(assignment_id=assignment.pk,
                task_id=number.pk, answer_number='7/3', auto_check='ok')
            interval = Task.objects.create(text_latex='Промежуток', answer_type='interval')
            parent = Submission.objects.create(assignment_id=assignment.pk, task_id=interval.pk)
            sub = apps.get_model('problems', 'TaskSubitem').objects.create(
                task_id=interval.pk, order=1, text_latex='Подпункт')
            part = apps.get_model('assignments', 'SubmissionPart').objects.create(
                submission_id=parent.pk, subitem_id=sub.pk,
                interval_low='-2', interval_high='3', auto_check='wrong')
            photo_only = Task.objects.create(text_latex='Только фото', answer_mode='extended', answer_mask='{{number: 4}}')
            photo_sub = apps.get_model('problems', 'TaskSubitem').objects.create(task=photo_only, text_latex='Подпункт', answer_mask='{{number: 5}}')
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            from problems.models import Task as NewTask, TaskSubitem as NewSub
            self.assertEqual(NewTask.objects.get(pk=photo_only.pk).answer_mask, '')
            self.assertEqual(NewSub.objects.get(pk=photo_sub.pk).answer_mask, '')
            self.assertFalse(NewTask.objects.get(pk=photo_only.pk).short_answer_available())
            from assignments.models import Submission as NewSubmission, SubmissionPart
            numeric = NewSubmission.objects.get(pk=numeric.pk)
            part = SubmissionPart.objects.get(pk=part.pk)
            self.assertEqual(numeric.display_answer, '7/3')
            self.assertEqual(numeric.answer_number, '7/3')
            self.assertEqual(numeric.auto_check, 'ok')
            self.assertEqual(part.display_answer, 'от -2 до 3')
            self.assertEqual(part.interval_low, '-2')
            self.assertEqual(part.auto_check, 'wrong')
            self.assertFalse(numeric.run_check())
            self.assertEqual(numeric.auto_check, 'ok')
        finally:
            MigrationExecutor(connection).migrate(current)
