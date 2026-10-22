"""Авторское указание не раскрывает ученику рисунок полного AI-решения."""
import re

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from problems.answer_material import answer_material
from problems.models import Task, TaskSubitem
from problems.task_images import classify_task_images
from problems.tests import make_teacher
from worksheets.latex import worksheet_to_tex
from worksheets.models import Worksheet, WorksheetItem


class MaterialImageTests(TestCase):
    def make_task(self, subitem=False):
        task = Task.objects.create(text_latex='Докажите утверждение.')
        owner = (TaskSubitem.objects.create(task=task, text_latex='Пункт', order=10)
                 if subitem else task)
        owner.author_answer_latex = 'Да.'
        owner.author_solution_latex = r'Указание. Проведите диагональ.\taskpic{1}'
        owner.solution_latex = r'Из равенства треугольников следует равенство сторон.\taskpic{2}'
        owner.save()
        author = task.images.create(image='task_images/author-hint.png', order=10)
        ai = task.images.create(image='task_images/ai-proof.png', order=20)
        return task, owner, author, ai

    def test_hint_and_ai_images_stay_with_their_sources(self):
        for subitem in (False, True):
            with self.subTest(subitem=subitem):
                task, _, author, ai = self.make_task(subitem)
                self.assertEqual(classify_task_images(task), ([], [author, ai]))
                material = answer_material(task)
                self.assertEqual(material['answer']['rows'][0]['images'], [])
                row = material['solution']['rows'][0]
                self.assertEqual(row['images'], [author])
                self.assertEqual(row['alt_images'], [ai])
                html = render_to_string('problems/_task_answers.html', {
                    'task': task, 'subitems': task.subitems.all()})
                alt = re.search(r'<details class="answer-alt" data-src="ai">.*?</details>',
                                html, re.S).group()
                author_url = reverse('task_image_file', args=[author.pk])
                ai_url = reverse('task_image_file', args=[ai.pk])
                self.assertIn(ai_url, alt)
                self.assertNotIn(author_url, alt)
                self.assertNotIn(ai_url, html.replace(alt, ''))
                self.assertEqual(html.count(author_url), 1)
                self.assertEqual(html.count(ai_url), 1)

    def test_hidden_answer_and_shared_images_have_stable_ownership(self):
        task = Task.objects.create(
            text_latex=r'Условие.\taskpic{1}',
            author_answer_latex=r'Авторский ответ.\taskpic{2}',
            answer_latex=r'AI-вариант.\taskpic{3}',
            solution_latex=r'AI-решение.\taskpic{1}\taskpic{2}\taskpic{4}')
        pics = [task.images.create(image=f'task_images/p{i}.png', order=i)
                for i in range(1, 5)]
        self.assertEqual(classify_task_images(task), ([pics[0]], pics[1:]))
        material = answer_material(task)
        self.assertEqual(material['answer']['rows'][0]['images'], [pics[1]])
        self.assertEqual(material['answer']['rows'][0]['alt_images'], [pics[2]])
        self.assertEqual(material['solution']['rows'][0]['images'], [pics[3]])

    def test_card_shows_answer_images_with_answers_not_in_condition(self):
        """Мерзляк 6.16: рисунки графиков из ответов подпунктов не стоят
        в «Условии» карточки, а показываются у своего ответа/решения."""
        task = Task.objects.create(text_latex=r'Постройте график.\taskpic{1}')
        first = TaskSubitem.objects.create(
            task=task, order=10, text_latex='$y=|x|$',
            author_answer_latex=r'\taskpic{2}', solution_latex=r'Строим.\taskpic{2}')
        TaskSubitem.objects.create(
            task=task, order=20, text_latex='$y=|x-1|$', solution_latex=r'Сдвиг.\taskpic{3}')
        pics = [task.images.create(image=f'task_images/g{i}.png', order=i)
                for i in range(1, 4)]
        self.client.force_login(make_teacher())
        html = self.client.get(reverse('task_detail', args=[task.pk])).content.decode()
        start = html.index('task-png-heading')
        condition = html[start:html.index('</section>', start)]
        urls = [reverse('task_image_file', args=[pic.pk]) for pic in pics]
        self.assertIn(urls[0], condition)
        self.assertNotIn(urls[1], condition)
        self.assertNotIn(urls[2], condition)
        answers = html[html.index(f'data-answer-owner="{first.pk}"'):]
        self.assertEqual(answers.count(f'src="{urls[1]}"'), 1)
        self.assertEqual(answers.count(f'src="{urls[2]}"'), 1)

    def test_pdf_hint_keeps_full_solution_and_respects_variants(self):
        teacher = make_teacher()
        for subitem in (False, True):
            with self.subTest(subitem=subitem):
                task, _, _, _ = self.make_task(subitem)
                worksheet = Worksheet.objects.create(title='Проверка рисунков', owner=teacher)
                WorksheetItem.objects.create(worksheet=worksheet, task=task, order=10)
                for variant in ('student', 'answers'):
                    tex = worksheet_to_tex(worksheet, variant)
                    self.assertNotIn('author-hint.png', tex)
                    self.assertNotIn('ai-proof.png', tex)
                tex = worksheet_to_tex(worksheet, 'teacher')
                self.assertEqual(tex.count('author-hint.png'), 1)
                self.assertEqual(tex.count('ai-proof.png'), 1)
                self.assertIn('Проведите диагональ.', tex)
                self.assertIn('Полное решение от AI.', tex)
                self.assertIn('Из равенства треугольников', tex)

    def test_unselected_subitem_never_leaks_hidden_ai_picture(self):
        task, _, _, _ = self.make_task(subitem=True)
        selected = TaskSubitem.objects.create(task=task, text_latex='Другой пункт', order=20)
        worksheet = Worksheet.objects.create(title='Выбор', owner=make_teacher())
        item = WorksheetItem.objects.create(worksheet=worksheet, task=task,
                                            order=10, all_subitems=False)
        item.subitems.set([selected])
        for variant in ('student', 'answers', 'teacher'):
            tex = worksheet_to_tex(worksheet, variant)
            self.assertNotIn('author-hint.png', tex)
            self.assertNotIn('ai-proof.png', tex)
            self.assertNotIn('Из равенства треугольников', tex)

    def test_graph_only_answer_points_to_picture_without_changing_author(self):
        task = Task.objects.create(text_latex='Постройте график.',
                                   author_answer_latex=r'\taskpic{1}')
        task.images.create(image='task_images/graph-only.png', order=1)
        worksheet = Worksheet.objects.create(title='График', owner=make_teacher())
        WorksheetItem.objects.create(worksheet=worksheet, task=task, order=1)
        for variant in ('answers', 'teacher'):
            tex = worksheet_to_tex(worksheet, variant)
            self.assertIn('См. рисунок.', tex)
            self.assertEqual(tex.count('graph-only.png'), 1)
        self.assertNotIn('graph-only.png', worksheet_to_tex(worksheet, 'student'))
        task.refresh_from_db()
        self.assertEqual(task.author_answer_latex, r'\taskpic{1}')

    def test_graph_reference_after_inequality_stays_outside_web_formula(self):
        task = Task.objects.create(text_latex='Постройте график.',
            answer_latex=r'Луч $y=x$, $x\ge1$.\taskpic{1}')
        picture = task.images.create(image='task_images/ray.png', order=1)
        html = render_to_string('problems/_task_answers.html', {'task': task})
        self.assertNotIn(r'\taskpic', html)
        self.assertIn(r'$x\ge1$', html)
        self.assertEqual(html.count(reverse('task_image_file', args=[picture.pk])), 1)
