from unittest import mock

from django.test import TestCase
from django.urls import reverse

from problems.models import Task
from problems.tests import make_student, make_teacher

from .latex import task_to_tex, worksheet_to_tex
from .models import ShareLink, Worksheet, WorksheetItem, WorksheetPdf


def make_worksheet(owner, title='Квадратные уравнения', n_tasks=2):
    worksheet = Worksheet.objects.create(
        title=title, grade_label='8 класс', owner=owner)
    for i in range(n_tasks):
        task = Task.objects.create(
            text_latex=f'Решите уравнение $x^2-{i + 2}x={i}$.',
            answer_latex=f'{i}; {i + 2}', stars=1, created_by=owner)
        WorksheetItem.objects.create(
            worksheet=worksheet, task=task, order=(i + 1) * 10)
    return worksheet


class LatexGenerationTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()

    def test_task_to_tex_full(self):
        task = Task.objects.create(
            text_latex='Вычислите:', subitems_latex='\\item $2+2$;',
            columns=2, answer_latex='4', solution_latex='Очевидно.', stars=1)
        tex = task_to_tex(task)
        self.assertIn('\\task{1}{2}{%', tex)
        self.assertIn('[{\\item $2+2$;}]', tex)
        self.assertIn('[{4}]', tex)
        self.assertIn('[{Очевидно.}]', tex)

    def test_task_to_tex_omits_trailing_args(self):
        task = Task.objects.create(text_latex='Просто задача')
        tex = task_to_tex(task)
        self.assertNotIn('[', tex.replace('\\[', ''))

    def test_answer_with_brackets_is_protected(self):
        task = Task.objects.create(
            text_latex='Неравенство', answer_latex='$x \\in [1; 2]$')
        tex = task_to_tex(task)
        self.assertIn('[{$x \\in [1; 2]$}]', tex)

    def test_worksheet_variants(self):
        worksheet = make_worksheet(self.teacher)
        student_tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn('\\usepackage{egor}', student_tex)
        self.assertIn('\\bighead{Квадратные уравнения}{8 класс}', student_tex)
        self.assertIn('\\rubr{Задачи}', student_tex)
        self.assertIn('\\end{enumerate}', student_tex)

        answers_tex = worksheet_to_tex(worksheet, 'answers')
        self.assertIn('\\usepackage[answers=table]{egor}', answers_tex)

        teacher_tex = worksheet_to_tex(worksheet, 'teacher')
        self.assertIn('\\usepackage[answers=inline,solutions]{egor}',
                      teacher_tex)

    def test_rubric_grouping(self):
        worksheet = make_worksheet(self.teacher, n_tasks=3)
        items = list(worksheet.ordered_items())
        items[0].rubric = 'Разминка'
        items[0].save()
        items[2].rubric = 'Основная часть'
        items[2].rubric_note = 'Решаем письменно'
        items[2].save()
        tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn('\\rubr{Разминка}', tex)
        self.assertIn('\\rubr{Основная часть}[{Решаем письменно}]', tex)
        self.assertEqual(tex.count('\\rubr'), 2)

    def test_header_escaping(self):
        worksheet = Worksheet.objects.create(
            title='Проценты & дроби 50%', grade_label='7_класс',
            owner=self.teacher)
        tex = worksheet_to_tex(worksheet, 'student')
        self.assertIn(r'Проценты \& дроби 50\%', tex)
        self.assertIn(r'7\_класс', tex)


class WorksheetViewTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.other_teacher = make_teacher('teacher2')
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher)

    def login_teacher(self):
        self.client.login(username='teacher1', password='pass12345')

    def test_builder_owner_only(self):
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 404)

    def test_add_and_move_and_remove_task(self):
        self.login_teacher()
        task = Task.objects.create(text_latex='Новая задача')
        self.client.post(
            reverse('worksheet_add_task', args=[self.worksheet.pk]),
            {'task_id': task.pk})
        items = list(self.worksheet.ordered_items())
        self.assertEqual(items[-1].task, task)

        self.client.post(reverse(
            'worksheet_move_item',
            args=[self.worksheet.pk, items[-1].pk, 'up']))
        items2 = list(self.worksheet.ordered_items())
        self.assertEqual(items2[1].task, task)

        self.client.post(reverse(
            'worksheet_remove_item', args=[self.worksheet.pk, items2[1].pk]))
        self.assertEqual(self.worksheet.items.count(), 2)

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_pdf_generation_and_cache(self, mocked):
        self.login_teacher()
        url = reverse('worksheet_pdf', args=[self.worksheet.pk])
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(mocked.call_count, 1)

        # Повторный запрос без изменений — из кэша
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked.call_count, 1)

        # Изменение листка → перегенерация
        item = self.worksheet.ordered_items()[0]
        item.rubric = 'Новая рубрика'
        item.save()
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(
            WorksheetPdf.objects.filter(worksheet=self.worksheet).count(), 1)

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_student_pdf_access(self, mocked):
        from assignments.models import Assignment
        Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher)
        self.client.login(username='student1', password='pass12345')
        url = reverse('worksheet_pdf', args=[self.worksheet.pk])
        response = self.client.get(url, {'variant': 'student'})
        self.assertEqual(response.status_code, 200)
        # Вариант с ответами ученику запрещён
        response = self.client.get(url, {'variant': 'teacher'})
        self.assertEqual(response.status_code, 403)


class ShareLinkTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        self.link = ShareLink.objects.create(worksheet=self.worksheet)

    def test_public_page_without_login(self):
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertContains(response, 'Квадратные уравнения')
        # Ответы не показываются
        self.assertNotContains(response, 'Ответ')

    def test_inactive_link_404(self):
        self.link.is_active = False
        self.link.save()
        response = self.client.get(
            reverse('public_worksheet', args=[self.link.token]))
        self.assertEqual(response.status_code, 404)

    def test_wrong_token_404(self):
        response = self.client.get(
            reverse('public_worksheet', args=['nonexistent-token']))
        self.assertEqual(response.status_code, 404)

    @mock.patch('worksheets.services.compile_latex',
                return_value=b'%PDF-1.5 fake')
    def test_public_pdf(self, mocked):
        response = self.client.get(
            reverse('public_worksheet_pdf', args=[self.link.token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
