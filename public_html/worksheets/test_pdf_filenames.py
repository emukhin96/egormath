"""Имена PDF листка: предмет и класс в начале, сокращённое название."""
from django.contrib.auth.models import User
from django.test import TestCase

from problems.models import GradeBand, Task, TaskTopic, Topic

from .filenames import title_slug
from .models import Worksheet, WorksheetItem


class PdfFilenameTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('fn_teacher', password='x')

    def sheet(self, title='Подобие треугольников', grade=None, topics=()):
        worksheet = Worksheet.objects.create(
            title=title, owner=self.owner, grade=grade)
        worksheet.topics.set([Topic.objects.get(code=c) for c in topics])
        return worksheet

    def add_task(self, worksheet, code, grade=None):
        task = Task.objects.create(text_latex='Задача', grade_level=grade)
        TaskTopic.objects.create(task=task, topic=Topic.objects.get(code=code),
                                 role=TaskTopic.ROLE_PRIMARY)
        WorksheetItem.objects.create(
            worksheet=worksheet, task=task, order=worksheet.items.count())

    def test_subject_from_root_topic(self):
        self.assertEqual(self.sheet(grade=9, topics=['GEO']).pdf_filename(),
                         'geom9-podob_treug.pdf')
        self.assertEqual(self.sheet(grade=7, topics=['ALG.01']).pdf_filename(),
                         'alg7-podob_treug.pdf')
        self.assertEqual(self.sheet(grade=8, topics=['ARI']).pdf_filename(),
                         'math8-podob_treug.pdf')

    def test_statistics_and_probability(self):
        self.assertTrue(self.sheet(grade=7, topics=['STA.02'])
                        .pdf_filename().startswith('stat7-'))
        self.assertTrue(self.sheet(grade=8, topics=['STA.03'])
                        .pdf_filename().startswith('teorver8-'))

    def test_mixed_subjects_and_young_grades_are_math(self):
        self.assertTrue(self.sheet(grade=9, topics=['ALG', 'GEO'])
                        .pdf_filename().startswith('math9-'))
        # В 5–6 классах предмет один — математика
        self.assertTrue(self.sheet(grade=6, topics=['GEO'])
                        .pdf_filename().startswith('math6-'))

    def test_ten_eleven_is_ten(self):
        self.assertTrue(self.sheet(grade=11, topics=['ALG'])
                        .pdf_filename().startswith('alg10-'))

    def test_subject_and_grade_from_tasks(self):
        worksheet = self.sheet()
        self.add_task(worksheet, 'GEO', grade=8)
        self.add_task(worksheet, 'GEO', grade=8)
        self.add_task(worksheet, 'ALG', grade=9)
        self.assertEqual(worksheet.pdf_filename('answers'),
                         'geom8-podob_treug-otvety.pdf')

    def test_grade_from_single_band(self):
        worksheet = self.sheet(topics=['GEO'])
        worksheet.grade_bands.set([GradeBand.objects.get(code='GRADE_9')])
        self.assertTrue(worksheet.pdf_filename().startswith('geom9-'))

    def test_beamer_filename(self):
        self.assertEqual(self.sheet(grade=9, topics=['GEO']).beamer_filename(),
                         'geom9-podob_treug-prezentaciya.pdf')

    def test_title_slug(self):
        # Слово — 4 буквы, но не на гласную; служебные слова выпадают
        self.assertEqual(title_slug('Разложение на множители'), 'razl_mnozh')
        self.assertEqual(title_slug('Отрезки в треугольнике'), 'otrez_treug')
        # Не больше трёх слов
        self.assertEqual(title_slug('Пропорциональные отрезки в прямоугольном '
                                    'треугольнике'), 'prop_otrez_pryam')
        self.assertEqual(title_slug('§ 12. Степень'), '12_step')
        self.assertEqual(title_slug('Площадь'), 'plosch')
        self.assertEqual(title_slug('???'), '')
