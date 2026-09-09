"""Единый приоритет авторских ответов и решений на экране и в PDF."""
from django.test import TestCase
from django.urls import reverse

from assignments.models import Assignment
from worksheets.latex import task_to_tex
from worksheets.models import Worksheet, WorksheetItem
from .models import Task, TaskSubitem
from .tests import make_student, make_teacher


class AuthorPriorityTests(TestCase):
    def test_priority_and_blank_fallback_for_task_and_subitem(self):
        for model in (Task, TaskSubitem):
            for author in (' Авторское ', '', ' \n '):
                with self.subTest(model=model.__name__, author=author):
                    owner = model(author_answer_latex=author,
                                  author_solution_latex=author,
                                  answer_latex=' Редакторское ',
                                  solution_latex=' Редакторское ')
                    expected = author.strip() or 'Редакторское'
                    self.assertEqual(owner.effective_answer_latex, expected)
                    self.assertEqual(owner.effective_solution_latex, expected)

    def test_editor_review_and_pdf_use_author_solution(self):
        teacher = make_teacher()
        self.client.force_login(teacher)
        task = Task.objects.create(
            created_by=teacher, text_latex='Вычислите',
            author_answer_latex='Авторский ответ', answer_latex='AI ответ',
            author_solution_latex='Авторское решение', solution_latex='AI решение')
        editor = self.client.get(reverse('task_detail', args=[task.pk]))
        self.assertContains(editor, '<div class="math-content">Авторское решение</div>', html=True)
        task.subitems.create(order=1, text_latex='Подпункт',
                             author_answer_latex='Ответ автора подпункта',
                             answer_latex='AI ответ подпункта',
                             author_solution_latex='Решение автора подпункта',
                             solution_latex='AI решение подпункта')
        worksheet = Worksheet.objects.create(owner=teacher, title='Приоритет')
        item = WorksheetItem.objects.create(worksheet=worksheet, task=task, order=1)
        assignment = Assignment.objects.create(worksheet=worksheet,
            student=make_student(teacher), assigned_by=teacher)
        editor = self.client.get(reverse('task_detail', args=[task.pk]))
        self.assertContains(editor, '<div class="math-content">Решение автора подпункта</div>', html=True)
        review = self.client.get(reverse('review_assignment', args=[assignment.pk]))
        self.assertContains(review, 'Авторское решение')
        self.assertNotContains(review, 'AI решение')
        tex = task_to_tex(item)
        for text in ('Авторский ответ', 'Авторское решение',
                     'Ответ автора подпункта', 'Решение автора подпункта'):
            self.assertIn(text, tex)
        self.assertNotIn('AI ', tex)
