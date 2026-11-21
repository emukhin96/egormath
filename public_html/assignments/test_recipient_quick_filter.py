"""Быстрый фильтр «Кому» в «Листках» и «Заданиях» (assignments/recipient_filters.py):
группа — сегментами (много групп — списком), ученик — списком своей группы."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import StudentGroup
from problems.tests import make_student, make_teacher
from worksheets.tests import make_worksheet

from .models import Assignment
from .recipient_filters import SEG_GROUPS_MAX


class RecipientQuickFilterTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.ann = make_student(self.teacher, 'ann')
        self.bob = make_student(self.teacher, 'bob')
        self.solo = make_student(self.teacher, 'solo')
        self.idle = make_student(self.teacher, 'idle')
        self.group = StudentGroup.objects.create(teacher=self.teacher, name='8 Б')
        self.group.students.add(self.ann, self.bob)
        # Группа без выданных работ в фильтре не показывается
        StudentGroup.objects.create(teacher=self.teacher, name='Кружок').students.add(self.idle)
        self.group_sheet = make_worksheet(self.teacher, title='Листок группы')
        self.solo_sheet = make_worksheet(self.teacher, title='Личный листок')
        make_worksheet(self.teacher, title='Невыданный листок')
        for student in (self.ann, self.bob):
            a = Assignment.objects.create(worksheet=self.group_sheet, student=student,
                                          assigned_by=self.teacher, recipient_origin_known=True)
            a.source_groups.add(self.group)
        Assignment.objects.create(worksheet=self.solo_sheet, student=self.solo,
                                  assigned_by=self.teacher, recipient_origin_known=True)
        self.client.login(username='teacher1', password='pass12345')

    def test_worksheet_list_filters_by_group_and_student(self):
        url = reverse('worksheet_list')
        full = self.client.get(url)
        self.assertContains(full, 'Кому')
        self.assertContains(full, '?group=%d' % self.group.pk)
        self.assertNotContains(full, 'Кружок')
        by_group = self.client.get(url, {'group': self.group.pk})
        titles = [w.title for w in by_group.context['worksheets']]
        self.assertEqual(titles, ['Листок группы'])
        # В списке учеников — только ученики группы
        self.assertEqual(by_group.context['recipient_filter']['students'], [self.ann, self.bob])
        by_student = self.client.get(url, {'student': self.solo.pk})
        self.assertEqual([w.title for w in by_student.context['worksheets']], ['Личный листок'])
        # Ученик не из выбранной группы не применяется
        mixed = self.client.get(url, {'group': self.group.pk, 'student': self.solo.pk})
        self.assertEqual([w.title for w in mixed.context['worksheets']], ['Листок группы'])

    def test_assignment_list_group_and_student(self):
        url = reverse('assignment_list')
        def titles(response):
            return [g['worksheet__title'] for g in response.context['worksheet_groups']]

        response = self.client.get(url, {'group': self.group.pk})
        self.assertEqual(titles(response), ['Листок группы'])
        self.assertContains(response, 'Сбросить')
        response = self.client.get(url, {'student': self.solo.pk})
        self.assertEqual(titles(response), ['Личный листок'])
        # Ученик — в строке «Кому», а не в «Ещё фильтры»
        self.assertNotContains(response, 'id="assignment-student"')

    def test_many_groups_become_select(self):
        for number in range(SEG_GROUPS_MAX):
            group = StudentGroup.objects.create(teacher=self.teacher, name=f'Группа {number}')
            group.students.add(self.solo)
        response = self.client.get(reverse('worksheet_list'))
        self.assertContains(response, '<select name="group"')
        self.assertNotContains(response, '?group=%d' % self.group.pk)
