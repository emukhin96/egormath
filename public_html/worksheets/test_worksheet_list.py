"""Список «Мои листки»: кому выдан листок, дата с днём недели, без класса и тем."""
from datetime import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentGroup
from assignments.models import Assignment
from assignments.views import _create_assignments
from problems.tests import make_student, make_teacher
from .models import Worksheet


class WorksheetListIssuedToTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.ws = Worksheet.objects.create(owner=self.teacher, title='Дроби')
        self.students = [make_student(self.teacher, username=f'pupil{i}') for i in range(4)]
        for index, student in enumerate(self.students):
            student.first_name = f'Ученик{index}'
            student.save()

    def give(self, students, groups=()):
        _create_assignments(
            worksheet=self.ws, teacher=self.teacher, students=students,
            check_visibility=Assignment.CHECK_LIVE, allow_photos=True, due_at=None,
            groups=groups, individual_ids=[s.pk for s in students if not groups])

    def row(self):
        response = self.client.get(reverse('worksheet_list'))
        return response, next(w for w in response.context['worksheets'] if w.pk == self.ws.pk)

    def test_group_shown_by_name_without_its_students(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        group.students.set(self.students[:3])
        self.give(self.students[:3], groups=[group])
        self.give([self.students[3]])
        response, row = self.row()
        self.assertEqual(row.issued_groups, ['8А'])
        self.assertEqual(row.issued_students, ['Ученик3 Ученик/ов'])
        self.assertContains(response, '<span class="ws-issued-group">8А</span>, Ученик3 Ученик/ов',
                            html=False)
        self.assertNotContains(response, 'Ученик0 Ученик/ов')

    def test_many_individual_students_collapse_to_count(self):
        self.give(self.students)
        response, row = self.row()
        self.assertEqual(row.issued_groups, [])
        self.assertEqual(len(row.issued_students), 4)
        self.assertContains(response, '4 ученика</span>')

    def test_not_issued_cell_is_empty(self):
        response = self.client.get(reverse('worksheet_list'))
        self.assertContains(response, '<td class="ws-list-issued"></td>', html=False)

    def test_other_teacher_group_with_same_students_is_ignored(self):
        """Старые выдачи без сохранённой группы сверяются только с группами
        владельца листка — чужая группа из тех же учеников не подставится."""
        other = make_teacher('teacher2')
        foreign = StudentGroup.objects.create(teacher=other, name='Чужая')
        foreign.students.set(self.students[:2])
        for student in self.students[:2]:
            Assignment.objects.create(worksheet=self.ws, student=student,
                                      assigned_by=self.teacher)
        _response, row = self.row()
        self.assertEqual(row.issued_groups, [])
        self.assertEqual(len(row.issued_students), 2)

    def test_queries_do_not_grow_with_worksheets(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        group.students.set(self.students[:2])
        self.give(self.students[:2], groups=[group])
        self.client.get(reverse('worksheet_list'))
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as before:
            self.client.get(reverse('worksheet_list'))
        for index in range(5):
            extra = Worksheet.objects.create(owner=self.teacher, title=f'Ещё {index}')
            Assignment.objects.create(worksheet=extra, student=self.students[3],
                                      assigned_by=self.teacher)
        with CaptureQueriesContext(connection) as after:
            self.client.get(reverse('worksheet_list'))
        self.assertEqual(len(after), len(before))


class WorksheetListColumnsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)

    def test_date_with_weekday_and_no_grade_or_topic_columns(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Степени')
        wednesday = timezone.make_aware(datetime(2026, 11, 18, 12, 0))
        Worksheet.objects.filter(pk=ws.pk).update(updated_at=wednesday)
        response = self.client.get(reverse('worksheet_list'))
        self.assertContains(response, '18.11.26, ср</time>')
        self.assertContains(response, '>Кому выдан</th>')
        self.assertContains(response, '>Задач</th>')
        self.assertNotContains(response, 'ws-list-grade')
        self.assertNotContains(response, 'ws-list-topics')
