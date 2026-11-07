"""Отметка «Ответ книги ошибочен»: исправленный ответ — основной везде.

Противоречия 06.11: карточка, листки и PDF брали ответ книги, даже когда
верный ответ уже записан в редакторское поле и маску, а AI-решение спорило
с ним. С отметкой основной — редакторский ответ и решение, ответ книги
остаётся серой строкой «В книге: …».
"""
from django.test import TestCase
from django.urls import reverse

from worksheets.latex import _combined_answer, _combined_solution

from .answer_material import answer_material, solution_texts
from .models import Task, TaskSubitem
from .tests import make_teacher


class AuthorAnswerWrongTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(
            text_latex='Найдите вероятность.',
            author_answer_latex='$0{,}8$', answer_latex='$0{,}75$',
            author_solution_latex='Книга: $16/20=0{,}8$.',
            solution_latex='$15/20=0{,}75$. Ответ: $0{,}75$')

    def test_book_answer_is_main_without_flag(self):
        self.assertEqual(self.task.effective_answer_latex, '$0{,}8$')
        self.assertEqual(self.task.wrong_book_answer, '')
        row = answer_material(self.task)['answer']['rows'][0]
        self.assertEqual((row['text'], row['source'], row['book']),
                         ('$0{,}8$', 'author', ''))

    def test_flag_makes_corrected_answer_and_solution_main(self):
        self.task.author_answer_wrong = True
        self.assertEqual(self.task.effective_answer_latex, '$0{,}75$')
        self.assertEqual(self.task.effective_solution_latex,
                         '$15/20=0{,}75$. Ответ: $0{,}75$')
        self.assertEqual(self.task.wrong_book_answer, '$0{,}8$')
        material = answer_material(self.task)
        row = material['answer']['rows'][0]
        self.assertEqual((row['text'], row['source'], row['alt'], row['book']),
                         ('$0{,}75$', 'ai', '', '$0{,}8$'))
        self.assertEqual(material['solution']['rows'][0]['text'],
                         '$15/20=0{,}75$. Ответ: $0{,}75$')
        self.assertEqual(solution_texts(self.task), ['$15/20=0{,}75$. Ответ: $0{,}75$'])

    def test_flag_without_editor_answer_keeps_book(self):
        self.task.author_answer_wrong = True
        self.task.answer_latex = ''
        self.assertEqual(self.task.effective_answer_latex, '$0{,}8$')
        self.assertEqual(self.task.wrong_book_answer, '')

    def test_pdf_answers_use_corrected_answer(self):
        self.task.author_answer_wrong = True
        self.task.save()
        self.assertIn('0{,}75', _combined_answer(self.task, []))
        self.assertNotIn('0{,}8', _combined_answer(self.task, []))
        self.assertIn('15/20', _combined_solution(self.task, []))
        self.assertNotIn('Книга', _combined_solution(self.task, []))

    def test_subitem_flag(self):
        sub = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='а',
            author_answer_latex='$2$', answer_latex='$3$', author_answer_wrong=True)
        self.assertEqual(sub.effective_answer_latex, '$3$')
        self.assertEqual(sub.wrong_book_answer, '$2$')
        copy = self.task.make_variant()
        self.assertTrue(copy.subitems.get().author_answer_wrong)

    def test_card_shows_corrected_answer_and_book_line(self):
        user = make_teacher('editor_wrong')
        self.task.created_by = user
        self.task.author_answer_wrong = True
        self.task.save()
        self.client.force_login(user)
        page = self.client.get(reverse('task_detail', args=[self.task.pk])).content.decode()
        self.assertIn('Исправленный', page)
        self.assertIn('В книге:', page)


class AuthorAnswerWrongCloneAndMaskTests(TestCase):
    """Ревью #324: клон и черновик маски не возвращают ошибочный ответ книги."""

    def setUp(self):
        self.task = Task.objects.create(
            text_latex='Найдите вероятность.', author_answer_latex='$0{,}8$',
            answer_latex='$0{,}75$', answer_mask='{{decimal: 0,75}}',
            author_answer_wrong=True)

    def test_clone_edits_corrected_answer_without_foreign_book_answer(self):
        from .clone import _apply_owner, _owner_data
        self.assertEqual(_owner_data(self.task, 'task', 'Условие')['answer_source'], 'editor')
        clone = self.task.make_variant(standalone=True)
        _apply_owner(self.task, clone, {'answer': '$0{,}7$', 'mask': '{{decimal: 0,7}}'}, True)
        clone.refresh_from_db()
        self.assertEqual((clone.author_answer_latex, clone.answer_latex), ('', '$0{,}7$'))
        self.assertFalse(clone.author_answer_wrong)
        self.assertEqual(clone.effective_answer_latex, '$0{,}7$')
        self.assertEqual(clone.wrong_book_answer, '')

    def test_mask_data_marks_wrong_book_answer(self):
        from .editor import mask_data
        self.assertTrue(mask_data(self.task)[0]['wrong_book'])
        self.task.author_answer_wrong = False
        self.task.save()
        self.assertFalse(mask_data(self.task)[0]['wrong_book'])


class AuthorAnswerWrongNoEditorSolutionTests(TestCase):
    """Ревью #324: без редакторского решения книжное (к ошибочному ответу) не показываем."""

    def test_book_solution_hidden(self):
        task = Task.objects.create(
            text_latex='Найдите вероятность.', author_answer_latex='$0{,}8$',
            answer_latex='$0{,}75$', author_solution_latex='Книга: $16/20=0{,}8$.',
            author_answer_wrong=True)
        self.assertEqual(task.effective_solution_latex, '')
        self.assertIsNone(answer_material(task)['solution'])
        self.assertEqual(solution_texts(task), [])
        self.assertNotIn('Книга', _combined_solution(task, []))


class AuthorAnswerWrongCloneKeepSolutionTests(TestCase):
    """Ревью #324: клон с «сохранить решение» не показывает книжное решение."""

    def test_clone_keeps_editor_solution_only(self):
        from .clone import _apply_owner
        task = Task.objects.create(
            text_latex='Найдите вероятность.', author_answer_latex='$0{,}8$',
            answer_latex='$0{,}75$', author_solution_latex='Книга: $16/20=0{,}8$.',
            solution_latex='$15/20=0{,}75$.', author_answer_wrong=True)
        clone = task.make_variant(standalone=True)
        _apply_owner(task, clone, {'answer': '$0{,}7$', 'mask': '{{decimal: 0,7}}'}, True)
        clone.refresh_from_db()
        self.assertEqual(clone.author_solution_latex, '')
        self.assertEqual(clone.effective_solution_latex, '$15/20=0{,}75$.')
        self.assertNotIn('Книга', ' '.join(solution_texts(clone)))
