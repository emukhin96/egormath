"""Регрессии независимого прогресса подпунктов и доступа к истории."""
from django.test import TestCase
from django.urls import reverse
from accounts.models import StudentGroup
from problems.models import Task
from problems.tests import make_teacher, make_student
from worksheets.models import Worksheet, WorksheetItem
from .models import Assignment, SubmissionCheckAttempt
from .point_progress import point_progress


class PointProgressTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.task = Task.objects.create(text_latex='Общее условие', created_by=self.teacher)
        self.a = self.task.subitems.create(order=1, text_latex='Первый пункт', answer_mask='{{number: 4}}')
        self.b = self.task.subitems.create(order=2, text_latex='Второй пункт', answer_mask='{{number: 8}}')
        self.ws = Worksheet.objects.create(owner=self.teacher, title='Пункты')
        self.item = WorksheetItem.objects.create(worksheet=self.ws, task=self.task)
        self.assignment = Assignment.objects.create(worksheet=self.ws, student=self.student, assigned_by=self.teacher)
        self.client.force_login(self.student)
        self.check_url = reverse('check_task', args=[self.assignment.pk, self.task.pk])
        self.url = reverse('worksheet_progress', args=[self.ws.pk])

    def answer(self, a='4', b='', check=True):
        url = self.check_url if check else reverse('save_answers', args=[self.assignment.pk])
        return self.client.post(url, {f'task{self.task.pk}_sub{self.a.pk}_s1': a,
                                     f'task{self.task.pk}_sub{self.b.pk}_s1': b})

    def summary(self, part):
        return point_progress(self.assignment.submissions.get(), part, is_part=True)

    def test_points_check_independently_without_counting_neighbours(self):
        self.answer(b='3')
        self.assertEqual((self.summary(self.a)['status'], self.summary(self.a)['attempt_count']), ('ok', 1))
        self.assertEqual(self.summary(self.b)['status'], 'wrong')
        self.answer(b='8')
        self.assertEqual(self.summary(self.a)['attempt_count'], 1)
        self.assertEqual((self.summary(self.b)['status'], self.summary(self.b)['attempt_count']), ('ok', 2))
        self.client.force_login(self.teacher)
        response = self.client.get(self.url)
        self.assertEqual(response.context['people'][0]['result'], {'done': 2, 'total': 2})
        self.assertContains(response, '✓<sub>2</sub>', html=False)

    def test_empty_unchecked_and_changed_answers(self):
        self.answer()
        self.assertEqual(self.summary(self.b)['attempt_count'], 0)
        self.assertEqual(self.summary(self.b)['status'], 'empty')
        self.answer(a='5', b='8', check=False)
        self.assertEqual(self.summary(self.a)['status'], 'ok')
        self.assertTrue(self.summary(self.a)['current_changed'])
        self.assertEqual(self.summary(self.b)['status'], 'draft')
        self.assertEqual(self.summary(self.b)['attempt_count'], 0)

    def test_dialog_contains_condition_and_only_selected_history(self):
        self.answer(b='3')
        self.answer(b='8')
        self.client.force_login(self.teacher)
        url = reverse('task_attempts', args=[self.assignment.pk, self.task.pk])
        response = self.client.get(url, {'item': self.item.pk, 'subitem': self.b.pk})
        self.assertContains(response, 'Общее условие')
        self.assertContains(response, 'Второй пункт')
        self.assertEqual(response.context['point']['attempt_count'], 2)
        self.assertTrue(all(t['id'] == self.b.pk for h in response.context['row']['attempt_history'] for t in h.snapshot['targets']))
        self.assertEqual(self.client.get(url, {'item': self.item.pk, 'subitem': 999999}).status_code, 404)
        self.item.all_subitems = False
        self.item.save()
        self.item.subitems.set([self.a])
        self.assertEqual(self.client.get(url, {'item': self.item.pk, 'subitem': self.b.pk}).status_code, 404)

    def test_etag_changes_when_selection_changes_and_after_autosave(self):
        self.answer()
        self.client.force_login(self.teacher)
        original = self.client.get(self.url, {'fragment': 1})
        self.assertEqual(self.client.get(self.url, {'fragment': 1}, HTTP_IF_NONE_MATCH=original['ETag']).status_code, 304)
        self.client.force_login(self.student)
        self.answer(a='5', check=False)
        self.client.force_login(self.teacher)
        changed = self.client.get(self.url, {'fragment': 1}, HTTP_IF_NONE_MATCH=original['ETag'])
        self.assertEqual(changed.status_code, 200)
        self.item.all_subitems = False
        self.item.save()
        self.item.subitems.set([self.b])
        self.assertEqual(self.client.get(self.url, {'fragment': 1}, HTTP_IF_NONE_MATCH=changed['ETag']).status_code, 200)

    def test_legacy_aggregate_is_not_result_of_every_part(self):
        self.answer(check=False)
        sub = self.assignment.submissions.get()
        SubmissionCheckAttempt.objects.create(submission=sub, number=1, result='ok')
        self.assertEqual(self.summary(self.a)['status'], 'draft')
        self.assertEqual(self.summary(self.a)['attempt_count'], 0)

    def test_overview_permissions_and_student_links(self):
        self.client.force_login(self.teacher)
        url = reverse('progress_overview')
        group = StudentGroup.objects.create(teacher=self.teacher, name='Группа')
        group.students.add(self.student)
        self.assertContains(self.client.get(url, {'group': group.pk}), self.ws.title)
        self.assertContains(self.client.get(url, {'student': self.student.pk}), reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(self.client.get(reverse('students')), '?student='+str(self.student.pk))
        other = make_teacher('other')
        self.client.force_login(other)
        self.assertEqual(self.client.get(url, {'group': group.pk}).status_code, 404)
        self.assertEqual(self.client.get(url, {'student': self.student.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_single_task_keeps_repeated_button_presses(self):
        from .models import Submission
        task = Task.objects.create(text_latex='Без подпунктов', answer_mask='{{number: 4}}')
        sub = Submission.objects.create(assignment=self.assignment, task=task, answer_json={'s1': '3'})
        for number in (1, 2):
            SubmissionCheckAttempt.objects.create(submission=sub, number=number, result='wrong',
                snapshot={'targets': [{'kind': 'task', 'id': task.pk, 'answer': sub.display_answer, 'result': 'wrong'}]})
        self.assertEqual(point_progress(sub, task)['attempt_count'], 2)

    def test_student_mini_tables_live_and_grouped_assignments(self):
        self.answer(b='3')
        self.answer(b='8')
        self.answer(b='3', check=False)
        self.client.force_login(self.teacher)
        url = reverse('progress_overview')
        response = self.client.get(url, {'student': self.student.pk})
        self.assertContains(response, 'data-progress-overview')
        self.assertContains(response, '✓<sub>2</sub>')
        self.assertContains(response, 'Текущий ввод изменён после проверки')
        fragment = self.client.get(url, {'student': self.student.pk, 'fragment': 1})
        self.assertEqual(self.client.get(url, {'student': self.student.pk, 'fragment': 1}, HTTP_IF_NONE_MATCH=fragment['ETag']).status_code, 304)
        self.client.force_login(self.student)
        self.answer(b='3')
        self.client.force_login(self.teacher)
        changed = self.client.get(url, {'student': self.student.pk, 'fragment': 1}, HTTP_IF_NONE_MATCH=fragment['ETag'])
        self.assertContains(changed, '×<sub>3</sub>')
        second = make_student(self.teacher, 'second')
        Assignment.objects.create(worksheet=self.ws, student=second, assigned_by=self.teacher)
        listed = self.client.get(reverse('assignment_list'))
        self.assertEqual(len(listed.context['worksheet_groups']), 1)
        self.assertEqual(listed.context['worksheet_groups'][0]['students_total'], 2)
        self.assertContains(listed, reverse('worksheet_progress', args=[self.ws.pk]))
