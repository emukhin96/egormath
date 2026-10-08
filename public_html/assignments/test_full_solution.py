"""Полное решение без фото и доски: сохранение и ручная проверка."""
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from problems.models import TaskSubitem
from problems.tests import make_student, make_teacher
from workaudit.models import AnswerRevision
from worksheets.tests import make_worksheet
from .models import Assignment, Submission, SubmissionPart


@override_settings(CANVAS_ENABLED=False)
class FullSolutionFallbackTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        worksheet = make_worksheet(self.teacher, n_tasks=1)
        self.task = worksheet.ordered_items()[0].task
        self.task.text_latex = 'Докажите утверждение.'
        self.task.answer_mask = ''
        self.task.save()
        self.assignment = Assignment.objects.create(
            worksheet=worksheet, student=self.student,
            assigned_by=self.teacher, allow_photos=False)
        self.client.force_login(self.student)
        self.detail = reverse('assignment_detail', args=[self.assignment.pk])
        self.save_url = reverse('save_answers', args=[self.assignment.pk])
        self.field = f'task{self.task.pk}_solution'

    def save(self, text, **extra):
        return self.client.post(self.save_url, {self.field: text, **extra},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_four_channel_configurations(self):
        for photos in (False, True):
            self.assignment.allow_photos = photos
            self.assignment.save()
            for board in (False, True):
                with self.subTest(photos=photos, board=board), override_settings(CANVAS_ENABLED=board):
                    response = self.client.get(self.detail)
                    if photos or board:
                        self.assertNotContains(response, f'name="{self.field}"')
                    else:
                        self.assertContains(response, f'name="{self.field}"')
                        self.assertContains(response, 'Его проверит учитель')

    def test_save_restore_and_no_machine_check(self):
        text = 'По признаку подобия $AB/CD=2$. Поэтому утверждение доказано.'
        with mock.patch('assignments.models.AnswerFields.run_check') as checker:
            response = self.save(text)
            checker.assert_not_called()
        self.assertEqual(response.status_code, 200)
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.answer_text, text)
        self.assertEqual(submission.answer_json, {})
        self.assertEqual(submission.auto_check, '')
        self.assertIsNone(submission.checked_at)
        self.assertEqual(submission.check_attempts, 0)
        self.assertFalse(submission.check_revealed)
        response = self.client.get(self.detail)
        self.assertContains(response, text)
        self.assertEqual(response.context['answered_count'], 1)
        self.assertEqual(AnswerRevision.objects.filter(submission=submission).count(), 1)

    def test_submit_without_autosave_and_teacher_view(self):
        text = 'Первый шаг.\nВторой шаг: $x=2$.'
        response = self.client.post(reverse('submit_assignment', args=[self.assignment.pk]),
                                    {self.field: text})
        self.assertEqual(response.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, 'Первый шаг.')
        self.assertContains(response, '$x=2$')
        self.assertFalse(response.context['rows'][0]['auto_ok'])

    def test_submitted_locked_and_returned_editable(self):
        self.save('Первое доказательство')
        self.assignment.status = Assignment.STATUS_SUBMITTED
        self.assignment.save()
        self.assertEqual(self.save('Замена после сдачи').status_code, 403)
        self.assertNotContains(self.client.get(self.detail), f'name="{self.field}"')
        self.assignment.status = Assignment.STATUS_RETURNED
        self.assignment.save()
        self.assertContains(self.client.get(self.detail), f'name="{self.field}"')
        self.save('Исправленное доказательство')
        self.assertEqual(Submission.objects.get(task=self.task).answer_text, 'Исправленное доказательство')

    def test_clear_and_absent_field_preserve_expected_state(self):
        self.save('Доказательство')
        self.client.post(self.save_url, {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(Submission.objects.get(task=self.task).answer_text, 'Доказательство')
        self.save('')
        submission = Submission.objects.get(task=self.task)
        self.assertEqual(submission.answer_text, '')
        self.assertEqual(self.client.get(self.detail).context['answered_count'], 0)
        self.assertEqual(AnswerRevision.objects.filter(submission=submission).count(), 2)

    def test_full_mode_overrides_reference_mask(self):
        self.task.answer_mask = '{{number: 90}}'
        self.task.full_answer_only = True
        self.task.save()
        self.assertContains(self.client.get(self.detail), f'name="{self.field}"')
        self.save('Доказательство равенства угла', **{f'task{self.task.pk}_s1': '90'})
        submission = Submission.objects.get(task=self.task)
        self.assertEqual(submission.answer_json, {})
        self.assertEqual(submission.auto_check, '')
        response = self.client.post(reverse('check_task', args=[self.assignment.pk, self.task.pk]),
                                    {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        submission.refresh_from_db()
        self.assertEqual(submission.check_attempts, 0)

    def test_working_short_mask_does_not_accept_solution_field(self):
        self.task.answer_mask = '{{number: 2}}'
        self.task.save()
        self.assertNotContains(self.client.get(self.detail), f'name="{self.field}"')
        self.save('Не короткий ответ')
        self.assertFalse(Submission.objects.filter(task=self.task).exists())

    def test_old_free_fields_still_rejected(self):
        self.client.post(self.save_url, {f'task{self.task.pk}_text': 'Старое поле'})
        self.assertFalse(Submission.objects.filter(task=self.task).exists())

    def test_mixed_parts_save_proof_without_auto_done_or_spent_attempt(self):
        proof = TaskSubitem.objects.create(task=self.task, order=10, text_latex='Докажите')
        numeric = TaskSubitem.objects.create(task=self.task, order=20, text_latex='Найдите', answer_mask='{{number: 2}}')
        proof_field = f'task{self.task.pk}_sub{proof.pk}_solution'
        numeric_field = f'task{self.task.pk}_sub{numeric.pk}_s1'
        response = self.client.get(self.detail)
        self.assertContains(response, f'name="{proof_field}"')
        self.assertContains(response, f'name="{numeric_field}"')
        self.client.post(self.save_url, {proof_field:'Доказательство', numeric_field:'2'})
        submission = Submission.objects.get(task=self.task)
        part = SubmissionPart.objects.get(submission=submission, subitem=proof)
        self.assertEqual(part.answer_text, 'Доказательство')
        self.assertEqual(part.auto_check, '')
        self.assertEqual(SubmissionPart.objects.get(subitem=numeric).auto_check, 'ok')
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertFalse(response.context['rows'][0]['auto_ok'])
        self.assertContains(response, 'Доказательство')
        self.client.force_login(self.student)
        response = self.client.post(reverse('check_task', args=[self.assignment.pk, self.task.pk]),
                                    {'check_subitem':str(proof.pk)}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['checks'], {})
        self.assertIn('проверит учитель', response.json()['message'])
        submission.refresh_from_db();part.refresh_from_db()
        self.assertEqual(submission.check_attempts, 0)
        self.assertFalse(part.check_revealed)

    def test_hidden_and_unselected_answers_ignored(self):
        item = self.assignment.worksheet.ordered_items()[0]
        self.assignment.hidden_items.add(item)
        self.save('Скрытая задача')
        self.assertFalse(Submission.objects.filter(task=self.task).exists())
        self.assignment.hidden_items.clear()
        a = TaskSubitem.objects.create(task=self.task, order=10, text_latex='Выбранный')
        b = TaskSubitem.objects.create(task=self.task, order=20, text_latex='Не выбранный')
        item.all_subitems = False
        item.save()
        item.subitems.add(a)
        self.client.post(self.save_url, {f'task{self.task.pk}_sub{b.pk}_solution':'Не выбранный'})
        self.assertFalse(SubmissionPart.objects.filter(subitem=b).exists())

    def test_html_is_escaped_when_restored(self):
        text = '</textarea><script>alert(1)</script>'
        self.save(text)
        response = self.client.get(self.detail)
        self.assertContains(response, escape(text))
        self.assertNotContains(response, text)

    def test_previous_mask_values_and_verdict_archived_on_full_mode(self):
        self.task.answer_mask = '{{number: 90}}'
        self.task.full_answer_only = True
        self.task.save()
        old = Submission.objects.create(assignment=self.assignment, task=self.task,
                                        answer_json={'s1':'90'}, auto_check='ok', check_revealed=True)
        self.client.force_login(self.teacher)
        review = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertFalse(review.context['rows'][0]['auto_ok'])
        self.client.force_login(self.student)
        self.save('Доказательство угла')
        old.refresh_from_db()
        self.assertEqual(old.display_answer, 'Доказательство угла')
        self.assertEqual(old.auto_check, '')
        self.assertTrue(AnswerRevision.objects.filter(submission=old, initial=True,
                                                     snapshot__answer_json={'s1':'90'}).exists())

    def test_legacy_unmasked_proof_does_not_make_mixed_task_auto_done(self):
        proof = TaskSubitem.objects.create(task=self.task, order=10, text_latex='Докажите')
        numeric = TaskSubitem.objects.create(task=self.task, order=20, text_latex='Найдите', answer_mask='{{number: 2}}')
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        SubmissionPart.objects.create(submission=submission, subitem=proof,
                                      answer_text='Старое доказательство', auto_check='ok')
        SubmissionPart.objects.create(submission=submission, subitem=numeric,
                                      answer_json={'s1':'2'}, auto_check='ok')
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertFalse(response.context['rows'][0]['auto_ok'])

    def test_empty_new_solution_does_not_erase_historical_mask(self):
        self.task.answer_mask = '{{number: 90}}'
        self.task.full_answer_only = True
        self.task.save()
        old = Submission.objects.create(assignment=self.assignment, task=self.task,
                                        answer_json={'s1':'90'})
        response = self.client.get(self.detail)
        self.assertContains(response, 'Ранее сохранённый короткий ответ')
        self.save('')
        old.refresh_from_db()
        self.assertEqual(old.answer_json, {'s1':'90'})
        self.assertFalse(AnswerRevision.objects.filter(submission=old).exists())

    def test_legacy_number_is_restored_in_full_solution_field(self):
        old = Submission.objects.create(assignment=self.assignment, task=self.task,
                                        answer_number='Исторический ответ')
        self.assertContains(self.client.get(self.detail), 'Исторический ответ</textarea>')
        self.save('Исправленное полное решение')
        old.refresh_from_db()
        self.assertEqual(old.display_answer, 'Исправленное полное решение')
        self.assertEqual(old.answer_number, '')
        self.assertTrue(AnswerRevision.objects.filter(submission=old, initial=True,
                                                     snapshot__answer_number='Исторический ответ').exists())
