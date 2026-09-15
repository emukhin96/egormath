"""Комментарии ссылок, выбор видимости и группировка адресатов листка."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import StudentGroup
from assignments.models import Assignment
from assignments.views import _create_assignments
from problems.models import Source, Task, TaskBlock
from problems.tests import make_student, make_teacher
from .models import ShareLink, Worksheet, WorksheetItem
from .recipients import assignment_sections, visibility_options


class RecipientControlsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.client.force_login(self.teacher)
        self.ws = Worksheet.objects.create(owner=self.teacher, title='Проверка адресатов')
        self.items = [WorksheetItem.objects.create(
            worksheet=self.ws, order=i, task=Task.objects.create(
                created_by=self.teacher, text_latex=f'Условие задачи {i}')) for i in (1, 2)]
        self.link = ShareLink.objects.create(worksheet=self.ws)
        self.assignment = Assignment.objects.create(
            worksheet=self.ws, student=self.student, assigned_by=self.teacher)

    def visibility_url(self, kind='link', recipient=None):
        return reverse('worksheet_recipient_visibility', args=[
            self.ws.pk, kind, (recipient or self.link).pk])

    def post(self, url, data):
        return self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_comment_is_private_and_can_be_cleared(self):
        url = reverse('share_comment', args=[self.ws.pk, self.link.pk])
        self.assertTrue(self.post(url, {'comment': 'Личная заметка для Анны'}).json()['ok'])
        self.link.refresh_from_db()
        self.assertEqual(self.link.comment, 'Личная заметка для Анны')
        self.assertContains(self.client.get(reverse('worksheet_detail', args=[self.ws.pk])), self.link.comment)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('public_worksheet', args=[self.link.token])), self.link.comment)
        self.client.force_login(self.teacher)
        self.assertEqual(self.post(url, {'comment': 'x' * 501}).status_code, 400)
        self.assertTrue(self.post(url, {'comment': ''}).json()['ok'])
        self.link.refresh_from_db()
        self.assertEqual(self.link.comment, '')

    def test_bulk_visibility_for_link_and_student(self):
        for kind, recipient in [('link', self.link), ('assignment', self.assignment)]:
            url = self.visibility_url(kind, recipient)
            self.assertContains(self.client.get(url), '№ 1')
            self.assertTrue(self.post(url, {'visible_items': [self.items[0].pk]}).json()['ok'])
            self.assertEqual(list(recipient.hidden_items.all()), [self.items[1]])
            self.assertTrue(self.post(url, {}).json()['ok'])
            self.assertEqual(recipient.hidden_items.count(), 2)
            self.assertTrue(self.post(url, {'visible_items': [i.pk for i in self.items]}).json()['ok'])
            self.assertFalse(recipient.hidden_items.exists())

    def test_visibility_reaches_public_and_student_pages(self):
        for kind, recipient in [('link', self.link), ('assignment', self.assignment)]:
            self.post(self.visibility_url(kind, recipient), {'visible_items': [self.items[0].pk]})
        response = self.client.get(reverse('public_worksheet', args=[self.link.token]))
        self.assertContains(response, 'Условие задачи 1')
        self.assertNotContains(response, 'Условие задачи 2')
        self.client.force_login(self.student)
        response = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'Условие задачи 1')
        self.assertNotContains(response, 'Условие задачи 2')

    def test_foreign_number_does_not_change_visibility(self):
        self.link.hidden_items.add(self.items[0])
        response = self.post(self.visibility_url(), {'visible_items': ['999999']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.link.hidden_items.all()), [self.items[0]])

    def test_other_teacher_and_student_cannot_manage_recipients(self):
        other = make_teacher('another_teacher')
        for user in [other, self.student]:
            self.client.force_login(user)
            for url in [self.visibility_url(), reverse('share_comment', args=[self.ws.pk, self.link.pk])]:
                self.assertIn(self.post(url, {'comment': 'Чужая правка'}).status_code, (403, 404))
        self.link.refresh_from_db()
        self.assertEqual(self.link.comment, '')
        self.assertFalse(self.link.hidden_items.exists())

    def test_recipient_must_belong_to_worksheet(self):
        other = Worksheet.objects.create(owner=self.teacher, title='Другой листок')
        link = ShareLink.objects.create(worksheet=other)
        self.assertEqual(self.post(self.visibility_url(recipient=link), {}).status_code, 404)

    def test_block_is_selected_as_a_whole(self):
        source = Source.objects.create(title='Источник')
        block = TaskBlock.objects.create(source=source, key='block', title='Общее условие', size=2)
        for i, item in enumerate(self.items, 1):
            item.task.block = block
            item.task.block_position = i
            item.task.save()
        options = visibility_options(self.ws, self.link)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['label'], '№ 1, 2')
        self.post(self.visibility_url(), {})
        self.assertEqual(self.link.hidden_items.count(), 2)
        self.post(self.visibility_url(), {'visible_items': [options[0]['value']]})
        self.assertFalse(self.link.hidden_items.exists())

    def test_removal_and_restore_support_json(self):
        rubric = WorksheetItem.objects.create(worksheet=self.ws, order=0, rubric='Домашняя работа')
        for item in [self.items[0], rubric]:
            response = self.post(reverse('worksheet_remove_item', args=[self.ws.pk, item.pk]), {})
            self.assertTrue(response.json()['ok'])
            item.refresh_from_db()
            self.assertIsNotNone(item.deleted_at)
            response = self.post(reverse('worksheet_restore_item', args=[self.ws.pk]), {})
            self.assertTrue(response.json()['ok'])
            item.refresh_from_db()
            self.assertIsNone(item.deleted_at)

    def test_legacy_group_requires_every_current_member(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='Группа девятого класса')
        second = make_student(self.teacher, 'second')
        group.students.add(self.student, second)
        sections, individuals = assignment_sections([self.assignment], [group])
        self.assertEqual(sections, [])
        self.assertEqual(individuals, [self.assignment])
        a2 = Assignment.objects.create(worksheet=self.ws, student=second)
        sections, individuals = assignment_sections([self.assignment, a2], [group])
        self.assertEqual(sections[0]['assignments'], [self.assignment, a2])
        self.assertEqual(individuals, [])

    def test_known_individual_is_not_inferred_into_group(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='Группа')
        group.students.add(self.student)
        self.assignment.recipient_origin_known = True
        sections, individuals = assignment_sections([self.assignment], [group])
        self.assertEqual(sections, [])
        self.assertEqual(individuals, [self.assignment])

    def test_new_group_origin_survives_membership_changes(self):
        second = make_student(self.teacher, 'second')
        group = StudentGroup.objects.create(teacher=self.teacher, name='Группа')
        group.students.add(second)
        _create_assignments(worksheet=self.ws, teacher=self.teacher, students=[second],
                            check_visibility=Assignment.CHECK_LIVE, allow_photos=True,
                            due_at=None, groups=[group])
        a = self.ws.assignments.get(student=second)
        self.assertTrue(a.recipient_origin_known)
        self.assertEqual(list(a.source_groups.all()), [group])
        group.students.clear()
        sections, individuals = assignment_sections([a], [group])
        self.assertEqual(sections[0]['group'], group)
        self.assertEqual(individuals, [])

    def test_explicit_individual_wins_and_reissue_preserves_origin(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='Группа')
        second = make_student(self.teacher, 'second')
        group.students.add(second)
        kwargs = dict(worksheet=self.ws, teacher=self.teacher, students=[second],
                      check_visibility=Assignment.CHECK_LIVE, allow_photos=True,
                      due_at=None, groups=[group])
        _create_assignments(**kwargs, individual_ids=[second.pk])
        _create_assignments(**kwargs)
        a = self.ws.assignments.get(student=second)
        self.assertTrue(a.recipient_origin_known)
        self.assertFalse(a.source_groups.exists())

    def test_both_issuance_routes_record_selected_group(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='Новая группа')
        second = make_student(self.teacher, 'new_group_student')
        group.students.add(second)
        for route in ['assign_worksheet', 'assignment_create']:
            ws = Worksheet.objects.create(owner=self.teacher, title=route)
            url = reverse(route, args=[ws.pk]) if route == 'assign_worksheet' else reverse(route)
            response = self.client.post(url, {
                'worksheet': ws.pk, 'groups': [group.pk],
                'check_visibility': Assignment.CHECK_LIVE, 'allow_photos': 'on',
            })
            self.assertEqual(response.status_code, 302)
            assignment = ws.assignments.get(student=second)
            self.assertTrue(assignment.recipient_origin_known)
            self.assertEqual(list(assignment.source_groups.all()), [group])

    def test_group_preserves_mixed_visibility_until_changed(self):
        second = make_student(self.teacher, 'second_group_student')
        other = Assignment.objects.create(worksheet=self.ws, student=second, assigned_by=self.teacher)
        group = StudentGroup.objects.create(teacher=self.teacher, name='Общая группа')
        group.students.add(self.student, second)
        self.assignment.hidden_items.add(self.items[0])
        url = self.visibility_url('group', group)
        self.assertContains(self.client.get(url), 'data-mixed')
        self.assertTrue(self.post(url, {'unchanged_items': [self.items[0].pk]}).json()['ok'])
        self.assertEqual(set(self.assignment.hidden_items.all()), set(self.items))
        self.assertEqual(list(other.hidden_items.all()), [self.items[1]])
        self.assertTrue(self.post(url, {'visible_items': [i.pk for i in self.items]}).json()['ok'])
        self.assertFalse(self.assignment.hidden_items.exists())
        self.assertFalse(other.hidden_items.exists())
        self.client.force_login(make_teacher('outsider_group_teacher'))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_invalid_status_keeps_visibility_and_valid_status_saves_together(self):
        url = self.visibility_url('assignment', self.assignment)
        self.assignment.hidden_items.add(self.items[0])
        for status in ('unknown', Assignment.STATUS_REVIEWED):
            self.assertEqual(self.post(url, {'status': status}).status_code, 400)
            self.assertEqual(list(self.assignment.hidden_items.all()), [self.items[0]])
        self.assertTrue(self.post(url, {'status': Assignment.STATUS_SUBMITTED,
                                       'visible_items': [self.items[0].pk]}).json()['ok'])
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        self.assertIsNotNone(self.assignment.submitted_at)
        self.assertEqual(list(self.assignment.hidden_items.all()), [self.items[1]])

    def test_status_cell_and_link_toggle_return_json(self):
        url = reverse('assignment_status_update', args=[self.assignment.pk])
        self.assertEqual(self.post(url, {'status': 'reviewed'}).status_code, 400)
        self.assertTrue(self.post(url, {'status': 'submitted'}).json()['ok'])
        self.assertTrue(self.post(url, {'status': 'reviewed'}).json()['ok'])
        response = self.post(reverse('share_toggle', args=[self.ws.pk, self.link.pk]), {})
        self.assertFalse(response.json()['is_active'])
        self.link.refresh_from_db()
        self.assertFalse(self.link.is_active)
        response = self.client.get(reverse('worksheet_detail', args=[self.ws.pk]))
        self.assertContains(response, 'data-progress-cell="status-')
        self.assertContains(response, 'contenteditable="plaintext-only"', count=2)
        self.assertNotContains(response, 'Полный экран прогресса')
