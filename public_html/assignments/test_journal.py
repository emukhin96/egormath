"""Журнал оценивания (макет D_Journal, assignments/journal.py): отметки и
проценты, опоздания, раскрытие работы по задачам, периоды, XLSX, группа."""
from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentGroup
from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .journal import mark_for, period_bounds
from .models import Assignment, Review, Submission, SubmissionCheckAttempt


class JournalTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.sheets = []
        for title in ('Подобие', 'Фалес'):
            sheet = make_worksheet(self.teacher)
            sheet.title = title
            sheet.save()
            WorksheetItem.objects.filter(worksheet=sheet).delete()
            for n in (1, 2):
                WorksheetItem.objects.create(worksheet=sheet, task=Task.objects.create(text_latex=f'{title} {n}', answer_mask='{{number: 3}}'), order=n)
            self.sheets.append(sheet)
        self.anna = make_student(self.teacher, username='anna')
        self.anna.last_name = 'Белова'
        self.anna.save()
        self.oleg = make_student(self.teacher, username='oleg')
        self.oleg.last_name = 'Жуков'
        self.oleg.save()
        now = timezone.now()
        past, future = now - timedelta(days=1), now + timedelta(days=3)
        tasks = [i.task for i in self.sheets[0].ordered_items()]
        a1 = Assignment.objects.create(worksheet=self.sheets[0], student=self.anna, due_at=future,
                                       status=Assignment.STATUS_REVIEWED, submitted_at=now)
        for task, grade in zip(tasks, ['+', '+-']):
            Review.objects.create(submission=Submission.objects.create(assignment=a1, task=task, answer_json={'s1': '3'}), grade=grade)
        self.o1 = Assignment.objects.create(worksheet=self.sheets[0], student=self.oleg, due_at=past - timedelta(days=1),
                                            status=Assignment.STATUS_SUBMITTED, submitted_at=past)
        Review.objects.create(submission=Submission.objects.create(assignment=self.o1, task=tasks[0], answer_json={'s1': '5'}), grade='-')
        sub = Submission.objects.create(assignment=self.o1, task=tasks[1], answer_json={'s1': '3'})
        SubmissionCheckAttempt.objects.create(submission=sub, number=1, result='wrong')
        SubmissionCheckAttempt.objects.create(submission=sub, number=2, result='ok')
        Assignment.objects.create(worksheet=self.sheets[1], student=self.anna, due_at=past)
        Assignment.objects.create(worksheet=self.sheets[1], student=self.oleg, due_at=future)
        self.url = reverse('assignment_journal')
        self.client.force_login(self.teacher)

    def rows(self, response):
        return {r['student'].username: r for r in response.context['rows']}

    def test_marks_and_late(self):
        response = self.client.get(self.url)
        self.assertEqual([w.title for w in response.context['works']], ['Подобие', 'Фалес'])
        rows = self.rows(response)
        anna, oleg = rows['anna'], rows['oleg']
        self.assertEqual([(c['kind'], c['mark'], c['percent']) for c in anna['cells']], [('done', '5', 88), ('missing', '', None)])
        # сдана после срока, но не проверена — «ждёт проверки», без отметки и не в среднем (ревью #283)
        self.assertEqual([(c['kind'], c['late'], c['mark']) for c in oleg['cells']], [('pending', True, ''), ('open', False, '')])
        self.assertEqual((anna['average'], anna['mark'], anna['late']), (88, '5', 1))
        self.assertEqual((oleg['average'], oleg['mark'], oleg['late']), (None, '', 1))
        self.assertContains(response, 'Журнал оценивания')
        self.assertContains(response, 'jr-work-cell jr-pending is-late')
        self.assertNotContains(response, '·')

    def test_open_by_tasks(self):
        response = self.client.get(self.url, {'open': self.sheets[0].pk})
        oleg = self.rows(response)['oleg']
        self.assertEqual([(t['kind'], t['sym'], t.get('sub', '')) for t in oleg['cells'][0]['tasks']], [('bad', '–', ''), ('auto', '✓', 2)])
        self.assertContains(response, 'Подобие, по задачам')
        self.assertContains(response, reverse('task_attempts', args=[self.o1.pk, self.o1.worksheet.ordered_items()[0].task_id]))

    def test_periods(self):
        self.assertEqual(period_bounds('quarter', date(2026, 10, 22)), (date(2026, 9, 1), date(2026, 11, 1)))
        self.assertEqual(period_bounds('quarter', date(2026, 12, 5)), (date(2026, 11, 1), date(2027, 1, 1)))
        self.assertEqual(period_bounds('quarter', date(2027, 2, 5)), (date(2027, 1, 1), date(2027, 4, 1)))
        self.assertEqual(period_bounds('half', date(2027, 2, 5)), (date(2027, 1, 1), date(2027, 9, 1)))
        self.assertEqual(period_bounds('prev_month', date(2027, 1, 10)), (date(2026, 12, 1), date(2027, 1, 1)))
        self.assertEqual(period_bounds('month', date(2026, 12, 10)), (date(2026, 12, 1), date(2027, 1, 1)))
        self.assertEqual((mark_for(85), mark_for(84), mark_for(45), mark_for(44), mark_for(None)), ('5', '4', '3', '2', ''))
        Assignment.objects.update(assigned_at=timezone.now() - timedelta(days=400))
        self.assertEqual(self.client.get(self.url).context['rows'], [])
        self.assertEqual(len(self.client.get(self.url, {'period': 'all'}).context['rows']), 2)

    def test_xlsx_group_and_access(self):
        response = self.client.get(self.url, {'format': 'xlsx'})
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        group = StudentGroup.objects.create(teacher=self.teacher, name='9 А')
        group.students.add(self.anna)
        self.assertEqual(list(self.rows(self.client.get(self.url, {'group': group.pk}))), ['anna'])
        self.client.force_login(make_teacher('stranger'))
        self.assertEqual(self.client.get(self.url).context['rows'], [])

    @override_settings(INDEPENDENT_WORKS_ENABLED=True)
    def test_nav(self):
        self.assertContains(self.client.get(reverse('dashboard')), self.url)


    def test_review_fixes(self):
        """Ревью #283: возвращённая без пересдачи после срока — не сдано и
        опоздание; номера раскрытой работы — как в листке; журнал в меню
        и без самостоятельных."""
        Assignment.objects.filter(pk=self.o1.pk).update(status=Assignment.STATUS_RETURNED,
                                                        submitted_at=self.o1.due_at - timedelta(hours=1))
        oleg = self.rows(self.client.get(self.url))['oleg']
        self.assertEqual((oleg['cells'][0]['kind'], oleg['cells'][0]['late']), ('missing', True))
        first = self.sheets[0].ordered_items()[0]
        for a in Assignment.objects.filter(worksheet=self.sheets[0]):
            a.hidden_items.add(first)
        response = self.client.get(self.url, {'open': self.sheets[0].pk})
        self.assertEqual([n for n, _ in response.context['opened_columns']], [2])
        self.assertContains(response, '№2</button>')
        with override_settings(INDEPENDENT_WORKS_ENABLED=False):
            self.assertContains(self.client.get(reverse('dashboard')), self.url)

    def test_xlsx_cells_are_text(self):
        """Ревью #283: название, начинающееся с «=», в XLSX — текст, не формула."""
        import io
        from openpyxl import load_workbook
        sheet = self.sheets[0]
        sheet.title = '=HYPERLINK("http://example.com","x")'
        sheet.save()
        response = self.client.get(self.url, {'format': 'xlsx'})
        book = load_workbook(io.BytesIO(b''.join(response.streaming_content)))
        header = book.active['B1']
        self.assertEqual((header.value, header.data_type), ('=HYPERLINK("http://example.com","x")', 's'))
