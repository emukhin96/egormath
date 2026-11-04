"""Кнопка доски «Вставить рисунок из условия»: только рисунки условия.

Регрессия: в задаче, где рисунок есть лишь в решении (\\taskpic в поле
решения), кнопка вставляла его на доску — и учителю, и ученику.
"""
import tempfile

from django.test import override_settings

from canvas.models import CanvasPage
from canvas.tests import CanvasBase
from canvas.tests import make_image
from canvas.tests import stroke


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StatementImagesOnBoardTests(CanvasBase):

    def setUp(self):
        super().setUp()
        self.statement = make_image(self.task, 'statement.png')
        self.solution = make_image(self.task, 'solution.png')
        self.statement.order, self.solution.order = 1, 2
        self.statement.save(update_fields=['order'])
        self.solution.save(update_fields=['order'])
        self.task.text_latex = 'Постройте график \\taskpic{1}'
        self.task.solution_latex = 'См. рисунок \\taskpic{2}'
        self.task.save(update_fields=['text_latex', 'solution_latex'])
        self.client.force_login(self.student)

    def img(self, source, element_id='i1'):
        return {'id': element_id, 't': 'img', 's': source, 'w': 1, 'c': '#000000',
                'p': [[100, 100], [500, 100], [100, 400]]}

    def test_solution_image_not_listed(self):
        data = self.client.get(self.url('pages')).json()
        self.assertEqual([i['id'] for i in data['images']], [self.statement.pk])

    def test_solution_only_task_has_no_button_images(self):
        self.task.text_latex = 'Постройте график'
        self.task.solution_latex = 'См. рисунок \\taskpic{1} и \\taskpic{2}'
        self.task.save(update_fields=['text_latex', 'solution_latex'])
        self.assertEqual(self.client.get(self.url('pages')).json()['images'], [])

    def test_solution_image_rejected_on_save(self):
        response = self.save(elements=[self.img(self.solution.pk)])
        self.assertEqual(response.status_code, 400)
        self.assertIn('условия этой задачи', response.json()['message'])
        self.assertEqual(self.save(elements=[self.img(self.statement.pk)]).status_code, 200)

    def test_already_placed_solution_image_does_not_lock_page(self):
        """Рисунок, вставленный старой кнопкой, не мешает дальше рисовать."""
        self.assertEqual(self.save(elements=[stroke()]).status_code, 200)
        page = CanvasPage.objects.get()
        page.student_elements = [self.img(self.solution.pk)]
        page.save(update_fields=['student_elements'])
        response = self.save(elements=[self.img(self.solution.pk), stroke('s2')], version=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.save(elements=[stroke('s3')], version=2).status_code, 200)
        # Удалённый с доски рисунок решения обратно уже не положить
        self.assertEqual(self.save(elements=[self.img(self.solution.pk)], version=3).status_code, 400)
