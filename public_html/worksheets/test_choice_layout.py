"""Варианты ответа остаются возле условия и сохраняют читаемый размер."""
from types import SimpleNamespace
from django.test import SimpleTestCase
from problems.models import Task
from .latex import _keep_choice_statement, task_to_tex


class ChoiceLayoutTests(SimpleTestCase):
    def test_short_teacher_question_keeps_its_answer(self):
        task = Task(id=1, text_latex='Найдите площадь комнаты.', answer_latex='$9$')
        task._prefetched_objects_cache = {'images': [], 'subitems': []}
        item = SimpleNamespace(task=task, selected_subitems=lambda: [], effective_columns=0, effective_stars=0)
        self.assertIn(r'\egorKeepAnswer', task_to_tex(item, 'teacher'))
        self.assertNotIn(r'\egorKeepAnswer', task_to_tex(item, 'student'))
        task.text_latex = 'Длинное условие. ' * 40
        self.assertNotIn(r'\egorKeepAnswer', task_to_tex(item, 'teacher'))

    def test_inline_strip_is_not_queued_and_text_choices_stay_together(self):
        source = 'Укажите решение системы неравенств\n\\[x>0\\]\n\\taskpic{strip.png}\\\\'
        result = _keep_choice_statement(source)
        self.assertNotIn(r'\taskpic',result)
        self.assertIn(r'\includegraphics[width=.9\linewidth',result)
        self.assertIn('{strip.png}',result)
        self.assertTrue(result.startswith(r'\begin{minipage}'))
        choices='Укажите решение системы неравенств\n1) A; 2) B; 3) C; 4) D.'
        self.assertIn(choices,_keep_choice_statement(choices))
        self.assertTrue(_keep_choice_statement(choices).endswith(r'\end{minipage}'))
        ordinary='Найдите угол.\\taskpic{triangle.png}'
        self.assertEqual(_keep_choice_statement(ordinary),ordinary)
        glued = source + r'\taskpic{second.png}'
        self.assertEqual(_keep_choice_statement(glued), glued)
        matching=('Установите соответствие между графиками и формулами.\n\n'
                  r'\taskpic{strip.png}'+'\n\nА & Б & В')
        self.assertIn(r'\includegraphics',_keep_choice_statement(matching))
        self.assertNotIn(r'\taskpic',_keep_choice_statement(matching))

    def test_student_does_not_receive_image_from_hidden_answer(self):
        task = Task(id=1, text_latex='Укажите решение системы неравенств\n1) A; 2) B; 3) C; 4) D.',
                    answer_latex=r'\taskpic{1}')
        task._prefetched_objects_cache = {
            'images': [SimpleNamespace(filename='answer.png')], 'subitems': []}
        item=SimpleNamespace(task=task,selected_subitems=lambda:[],effective_columns=0,effective_stars=0)
        result=task_to_tex(item,'student')
        self.assertNotIn('answer.png',result)
        self.assertIn(r'\begin{minipage}',result)
