"""Кабинет учителя: пять последних листков без GROUP BY по всем листкам
(аудит быстродействия 06.11.2026, раздел 6, пункт 9)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from accounts.views import recent_worksheets
from problems.models import Task
from worksheets.models import Worksheet, WorksheetItem


def make_teacher(username, **profile_fields):
    user = User.objects.create_user(username=username, password='pass12345',
                                    first_name='Иван', last_name='Учителев')
    Profile.objects.create(user=user, role=Profile.ROLE_TEACHER, **profile_fields)
    return user


class RecentWorksheetsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1', base_editor=True)
        self.other = make_teacher('teacher2')
        self.task = Task.objects.create(text_latex='Задача', created_by=self.teacher)
        # Семь листков учителя с разным числом задач; updated_at — auto_now,
        # поэтому порядок задаём явным update() после создания.
        self.sheets = []
        for i in range(7):
            sheet = Worksheet.objects.create(owner=self.teacher, title=f'Листок {i}')
            for order in range(i % 4):
                WorksheetItem.objects.create(worksheet=sheet, task=self.task, order=order)
            self.sheets.append(sheet)
        base = Worksheet.objects.order_by('-updated_at').first().updated_at
        for i, sheet in enumerate(self.sheets):
            Worksheet.objects.filter(pk=sheet.pk).update(
                updated_at=base + timedelta(minutes=i))
        foreign = Worksheet.objects.create(owner=self.other, title='Чужой')
        Worksheet.objects.filter(pk=foreign.pk).update(
            updated_at=base + timedelta(hours=1))

    def expected(self, user, limit=5):
        """Эталон — прежняя выборка с annotate, но с явной сортировкой."""
        from django.db.models import Count
        return [(w.pk, w.n) for w in Worksheet.visible_to(user)
                .annotate(n=Count('items')).order_by('-updated_at')[:limit]]

    def test_latest_five_with_item_counts(self):
        with self.assertNumQueries(2):
            rows = [(w.pk, w.items_total) for w in recent_worksheets(self.teacher)]
        self.assertEqual(rows, self.expected(self.teacher))
        self.assertEqual(len(rows), 5)
        # Самый свежий — первым, пустой листок считается нулём, а не пропадает
        self.assertEqual(rows[0][0], self.sheets[6].pk)
        self.assertIn((self.sheets[4].pk, 0), rows)

    def test_teacher_sees_only_own(self):
        pks = {w.pk for w in recent_worksheets(self.teacher)}
        self.assertTrue(all(Worksheet.objects.get(pk=pk).owner == self.teacher for pk in pks))
        self.assertEqual([w.pk for w in recent_worksheets(self.other)],
                         [Worksheet.objects.get(owner=self.other).pk])

    def test_superuser_sees_everyone_latest_first(self):
        admin = User.objects.create_superuser('admin', 'a@example.com', 'pass12345')
        rows = [(w.pk, w.items_total) for w in recent_worksheets(admin)]
        self.assertEqual(rows, self.expected(admin))
        self.assertEqual(rows[0][0], Worksheet.objects.get(owner=self.other).pk)

    def test_dashboard_renders_counts(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Листок 6')
        self.assertContains(response, '2 задачи')
        self.assertNotContains(response, 'Листок 0')
