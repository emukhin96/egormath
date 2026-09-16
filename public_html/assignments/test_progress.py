"""Оценивание и доступ к ответам до отправки работы."""
from django.test import TestCase
from django.urls import reverse
from problems.tests import make_teacher, make_student
from problems.models import Task
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from accounts.models import StudentGroup
from .models import Assignment, Review, Submission


class LiveProgressTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher)
        self.task = Task.objects.create(text_latex='Найдите число', answer_mask='{{number: 8}}')
        self.item = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=1)
        self.assignment = Assignment.objects.create(worksheet=self.worksheet, student=self.student, assigned_by=self.teacher)
        self.client.force_login(self.teacher)

    def test_fully_hidden_columns_removed_without_renumbering(self):
        from .progress import progress_groups
        second = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=2)
        self.assignment.hidden_items.add(self.item)
        groups = progress_groups([self.item, second], [self.assignment])
        self.assertEqual([group['number'] for group in groups], [2])
        other = Assignment.objects.create(worksheet=self.worksheet, student=make_student(self.teacher, username='visible_student'), assigned_by=self.teacher)
        self.assertEqual(len(progress_groups([self.item, second], [self.assignment, other])), 2)

    def grade(self, value):
        return self.client.post(reverse('grade_task', args=[self.assignment.pk, self.task.pk]), {'grade': value})

    def test_all_credits_and_unstarted_task(self):
        for value, score in [('+',1),('.+',1),('+-',.75),('=',.5),('-+',0),('.-',0),('-',0),('0',0)]:
            response = self.grade(value)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['result']['done'], score)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, 'assigned')

    def test_invalid_and_hidden_tasks(self):
        self.assertEqual(self.grade('excellent').status_code,400)
        self.assignment.hidden_items.add(self.item)
        self.assertEqual(self.grade('+').status_code,404)
        self.assertFalse(Review.objects.exists())

    def test_live_before_submit_and_access_control(self):
        sub=Submission.objects.create(assignment=self.assignment, task=self.task, answer_json={'s1':'8'})
        response=self.client.get(reverse('assignment_live',args=[self.assignment.pk]))
        self.assertContains(response,'8')
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('assignment_live',args=[self.assignment.pk])).status_code,403)
        self.assertEqual(self.grade('+').status_code,403)

    def test_matrix_and_attempts_before_submission(self):
        response=self.client.get(reverse('worksheet_progress',args=[self.worksheet.pk]))
        self.assertContains(response,'Не начато')
        response=self.client.get(reverse('task_attempts',args=[self.assignment.pk,self.task.pk]))
        self.assertContains(response,'Проверок пока нет')
        self.assertContains(response,'data-grade="="')

    def test_default_live_and_group_filter(self):
        self.assertEqual(self.assignment.check_visibility, 'live')
        group=StudentGroup.objects.create(teacher=self.teacher,name='Пустая группа')
        response=self.client.get(reverse('worksheet_progress',args=[self.worksheet.pk]), {'group':group.pk})
        self.assertContains(response,'Нет назначений')

    def test_duplicate_item_count_and_comment_preserves_grade(self):
        WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=2)
        self.assertEqual(self.grade('+-').json()['result']['done'],1.5)
        sub=Submission.objects.get(assignment=self.assignment,task=self.task)
        self.client.post(reverse('save_review',args=[self.assignment.pk]),{'grade_interface':'1',f'sub{sub.pk}_comment':'Обоснование'})
        self.assertEqual(Review.objects.get(submission=sub).grade,'+-')

    def test_answer_autosave_does_not_overwrite_concurrent_counter(self):
        from unittest.mock import patch
        sub = Submission.objects.create(assignment=self.assignment, task=self.task,
                                        answer_json={'s1':'7'}, check_attempts=2)
        original = Submission.run_check
        def concurrent_check(obj, *args, **kwargs):
            Submission.objects.filter(pk=obj.pk).update(check_attempts=3)
            return original(obj, *args, **kwargs)
        self.client.force_login(self.student)
        with patch.object(Submission, 'run_check', autospec=True, side_effect=concurrent_check):
            self.client.post(reverse('save_answers',args=[self.assignment.pk]), {f'task{self.task.pk}_s1':'8'})
        sub.refresh_from_db()
        self.assertEqual(sub.check_attempts,3)
        self.assertEqual(sub.answer_json,{'s1':'8'})

    def test_next_attempt_uses_history_when_counter_is_stale(self):
        from .models import SubmissionCheckAttempt
        sub=Submission.objects.create(assignment=self.assignment,task=self.task,answer_json={'s1':'8'},check_attempts=2)
        SubmissionCheckAttempt.objects.create(submission=sub,number=3,result='ok')
        self.client.force_login(self.student)
        response=self.client.post(reverse('check_task',args=[self.assignment.pk,self.task.pk]),{f'task{self.task.pk}_s1':'8'})
        self.assertEqual(response.status_code,302)
        sub.refresh_from_db()
        self.assertEqual(sub.check_attempts,4)
        self.assertTrue(sub.check_history.filter(number=4).exists())

    def test_grade_does_not_hide_check_and_symbols_are_typographic(self):
        from .models import SubmissionCheckAttempt
        self.grade('+-')
        sub=Submission.objects.get(assignment=self.assignment,task=self.task)
        SubmissionCheckAttempt.objects.create(submission=sub,number=1,result='wrong')
        response=self.client.get(reverse('worksheet_progress',args=[self.worksheet.pk]))
        self.assertContains(response,'Неверно')
        self.assertContains(response,'Оценка ±')
        response=self.client.get(reverse('task_attempts',args=[self.assignment.pk,self.task.pk]))
        self.assertContains(response,'>±</button>')
        self.assertContains(response,'>.–</button>')
        self.assertContains(response,'>–</button>')
        self.assertContains(response,'class="check-history" open')

    def test_duplicate_live_rows_have_item_keys_and_unchanged_rows_are_omitted(self):
        import json
        duplicate=WorksheetItem.objects.create(worksheet=self.worksheet,task=self.task,order=2)
        url=reverse('assignment_live',args=[self.assignment.pk])
        result=self.client.get(url).json()
        self.assertIn(str(self.item.pk),result['rows'])
        self.assertIn(str(duplicate.pk),result['rows'])
        self.assertEqual(self.client.get(url,{'versions':json.dumps(result['versions'])}).json()['rows'],{})
        response=self.client.get(reverse('review_assignment',args=[self.assignment.pk]))
        self.assertContains(response,f'data-live-answer="{duplicate.pk}"')

    def test_comment_before_first_answer(self):
        url=reverse('review_assignment',args=[self.assignment.pk])
        self.assertContains(self.client.get(url),f'name="task{self.task.pk}_comment"')
        self.client.post(reverse('save_review',args=[self.assignment.pk]),{'grade_interface':'1',f'task{self.task.pk}_comment':'Начни с рисунка'})
        review=Review.objects.get(submission__assignment=self.assignment,submission__task=self.task)
        self.assertEqual(review.comment,'Начни с рисунка')
        self.assertEqual(review.grade,'')

    def test_dialog_uses_item_and_etag(self):
        duplicate=WorksheetItem.objects.create(worksheet=self.worksheet,task=self.task,order=2)
        url=reverse('task_attempts',args=[self.assignment.pk,self.task.pk])
        response=self.client.get(url,{'item':duplicate.pk})
        self.assertEqual(response.context['row']['item'].pk,duplicate.pk)
        cached=self.client.get(url,{'item':duplicate.pk},HTTP_IF_NONE_MATCH=response['ETag'])
        self.assertEqual(cached.status_code,304)

    def test_matrix_etag(self):
        url=reverse('worksheet_progress',args=[self.worksheet.pk])
        response=self.client.get(url,{'fragment':'1'})
        self.assertEqual(self.client.get(url,{'fragment':'1'},HTTP_IF_NONE_MATCH=response['ETag']).status_code,304)
        self.grade('+')
        self.assertEqual(self.client.get(url,{'fragment':'1'},HTTP_IF_NONE_MATCH=response['ETag']).status_code,200)

    def test_attempt_keeps_renderable_fragments_without_reference(self):
        self.task.answer_mask='a = {{number: 1}}, b = {{number: 10}}'
        self.task.save()
        self.client.force_login(self.student)
        self.client.post(reverse('check_task',args=[self.assignment.pk,self.task.pk]),{f'task{self.task.pk}_s1':'1',f'task{self.task.pk}_s2':'10'})
        from .models import SubmissionCheckAttempt
        target=SubmissionCheckAttempt.objects.get(submission__task=self.task).snapshot['targets'][0]
        self.assertEqual([f['display'] for f in target['fragments'] if 'display' in f],['1','10'])
        self.assertTrue(all('slot' not in f for f in target['fragments']))
