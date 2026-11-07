"""Выданные работы секциями по получателям и переключатель «Задания /
Самостоятельные» (ответ Егора к Z2, 07.11)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentGroup
from problems.tests import make_student
from problems.tests import make_teacher
from worksheets.tests import make_worksheet

from .models import Assignment


class RecipientSectionsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.ann = make_student(self.teacher, 'ann')
        self.bob = make_student(self.teacher, 'bob')
        self.solo = make_student(self.teacher, 'solo')
        self.group = StudentGroup.objects.create(teacher=self.teacher, name='8 Б')
        self.group.students.add(self.ann, self.bob)
        now = timezone.now()
        self.old = make_worksheet(self.teacher, title='Старый листок')
        self.new = make_worksheet(self.teacher, title='Свежий листок')
        self.personal = make_worksheet(self.teacher, title='Личный листок')
        for sheet, when in ((self.old, now - timedelta(days=5)), (self.new, now - timedelta(days=1))):
            for student in (self.ann, self.bob):
                a = Assignment.objects.create(worksheet=sheet, student=student, assigned_by=self.teacher,
                                              recipient_origin_known=True)
                a.source_groups.add(self.group)
                Assignment.objects.filter(pk=a.pk).update(assigned_at=when)
        a = Assignment.objects.create(worksheet=self.personal, student=self.solo, assigned_by=self.teacher,
                                      recipient_origin_known=True)
        Assignment.objects.filter(pk=a.pk).update(assigned_at=now - timedelta(days=3))
        self.client.login(username='teacher1', password='pass12345')

    def test_sections_by_recipient_newest_first(self):
        response = self.client.get(reverse('assignment_list'))
        sections = response.context['recipient_sections']
        self.assertEqual([s['label'] for s in sections], ['8 Б', self.solo.get_full_name() or 'solo'])
        self.assertEqual([r['worksheet__title'] for r in sections[0]['rows']], ['Свежий листок', 'Старый листок'])
        self.assertEqual([r['worksheet__title'] for r in sections[1]['rows']], ['Личный листок'])
        self.assertContains(response, 'class="asg-section-head"')

    def test_kind_switch_has_two_positions(self):
        response = self.client.get(reverse('assignment_list'))
        self.assertEqual(response.context['filters']['kind'], 'ordinary')
        html = response.content.decode()
        self.assertNotIn('>Все</a>', html.split('aria-label="Вид работы"')[1].split('</nav>')[0])
        self.assertIn('>Задания</a>', html)

    def test_sections_follow_filters(self):
        """Фильтр по ученику: работа видна только под его секцией (ревью #326)."""
        response = self.client.get(reverse('assignment_list'), {'student': self.solo.pk})
        labels = [s['label'] for s in response.context['recipient_sections']]
        self.assertEqual(labels, [self.solo.get_full_name() or 'solo'])
        response = self.client.get(reverse('assignment_list'), {'student': self.ann.pk})
        sections = response.context['recipient_sections']
        self.assertTrue(all('solo' not in s['label'] for s in sections))
        self.assertEqual(sum(len(s['rows']) for s in sections), 2)

