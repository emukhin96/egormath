"""«Подборки» полками по классам (worksheets/collection_shelves.py) и разбор
класса и раздела источника по названию (problems/source_meta.py)."""
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from problems.models import Source, Task
from problems.source_meta import guess_grades, guess_subject
from problems.tests import make_teacher
from worksheets.collection_shelves import cover_name
from worksheets.corpus import SOURCE_TITLE as AUTHORED_SOURCE
from worksheets.models import Collection, Worksheet, WorksheetItem


class SourceMetaTests(SimpleTestCase):
    def test_grades_from_title(self):
        self.assertEqual(guess_grades('Алгебра. 7 класс. Дидактические материалы'), (7, 7))
        self.assertEqual(guess_grades('Дидактические материалы по теории вероятностей. 8–9 классы'), (8, 9))
        self.assertEqual(guess_grades('Шабунин 10-11'), (10, 11))
        self.assertEqual(guess_grades('Зив-8'), (8, 8))
        self.assertEqual(guess_grades('Открытый банк ОГЭ'), (9, 9))
        self.assertEqual(guess_grades('ЕГЭ-2027, профильный уровень'), (11, 11))
        self.assertEqual(guess_grades('Многогранники С2'), (None, None))

    def test_subject_from_title(self):
        self.assertEqual(guess_subject('Стереометрия ЕГЭ'), 'geometry')
        self.assertEqual(guess_subject('Математика. Алгебра. Начала анализа. 10 класс'), 'algebra')
        self.assertEqual(guess_subject('Математика — абитуриенту'), 'exams')
        self.assertEqual(guess_subject('Математика. 5 класс'), 'math')
        self.assertEqual(guess_subject('Дидактические материалы по теории вероятностей'), 'statistics')
        self.assertEqual(guess_subject('Зив-8'), '')

    def test_cover_name(self):
        self.assertEqual(cover_name(Source(title='Т', author='И. Р. Высоцкий')), 'Высоцкий')
        self.assertEqual(cover_name(Source(title='Зив-8')), 'Зив')
        self.assertEqual(cover_name(Source(title='Т', author='Мерзляк А. Г., Якир М. С.')), 'Мерзляк')


class CollectionShelvesTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.alg7 = self.book('Алгебра. 7 класс', 7, 7, 'algebra', author='Мерзляк А. Г.')
        self.geo8 = self.book('Зив-8', 8, 8, 'geometry', author='Б. Г. Зив')
        self.prob = self.book('Теория вероятностей. 8–9 классы', 8, 9, 'statistics')
        self.loose = self.book('Сборник без класса', None, None, '')
        authored = Source.objects.create(title=AUTHORED_SOURCE, author='Е. А. Мухин')
        self.section8 = self.collection(authored, '8 класс')
        self.collection(authored, 'ЕГЭ')

    def collection(self, source, title):
        sheet = Worksheet.objects.create(title=title, owner=self.owner)
        WorksheetItem.objects.create(
            worksheet=sheet, order=10,
            task=Task.objects.create(text_latex=f'{title}: задача', created_by=self.owner))
        return Collection.objects.create(worksheet=sheet, source=source,
                                         locator=title, is_published=True)

    def book(self, title, low, high, subject, author=''):
        source = Source.objects.create(title=title, author=author, grade_from=low,
                                       grade_to=high, subject=subject)
        self.collection(source, f'{title}, глава 1')
        return source

    def page(self, **params):
        return self.client.get(reverse('collection_list'), params)

    def shelf_titles(self, response):
        return {shelf['label']: [book['source'].title for book in shelf['books']]
                for shelf in response.context['shelves']['shelves']}

    def test_shelves_by_grade_with_authored_on_top(self):
        response = self.page()
        self.assertEqual(self.shelf_titles(response), {
            '7 класс': ['Алгебра. 7 класс'],
            '8 класс': ['Зив-8', 'Теория вероятностей. 8–9 классы'],
            '9 класс': ['Теория вероятностей. 8–9 классы'],
            'Без класса': ['Сборник без класса'],
        })
        spans = [shelf['span'] for shelf in response.context['shelves']['shelves']]
        self.assertEqual(spans, [1, 2, 1, 1])
        self.assertContains(response, 'class="authored-banner"')
        self.assertContains(response, reverse('collection_detail', args=[self.section8.pk]))
        # Авторские листки — не полка; числа задач на карточках нет
        self.assertNotIn(AUTHORED_SOURCE, str(self.shelf_titles(response)))
        self.assertNotContains(response, 'collection-source-stats')
        # Обложка-заглушка: класс и фамилия
        self.assertContains(response, '<span class="source-cover-name">Зив</span>')

    def test_grade_and_subject_filters(self):
        response = self.page(grade='8')
        self.assertEqual(self.shelf_titles(response),
                         {'8 класс': ['Зив-8', 'Теория вероятностей. 8–9 классы']})
        # Раздел листков «8 класс» подсвечен, «ЕГЭ» — нет
        sections = {s['collection'].catalog_title: s.get('active')
                    for s in response.context['shelves']['authored']['sections']}
        self.assertEqual(sections, {'8 класс': True, 'ЕГЭ': False})
        response = self.page(subject='geometry')
        self.assertEqual(self.shelf_titles(response), {'8 класс': ['Зив-8']})
        chips = {c['label']: c for c in response.context['shelves']['subject_chips']}
        self.assertTrue(chips['Геометрия']['active'])
        self.assertEqual(chips['Геометрия']['url'], '?')
        empty = self.page(subject='geometry', grade='7')
        self.assertContains(empty, 'Нет задачников по выбранным фильтрам')

    def test_unknown_filter_values_are_ignored(self):
        response = self.page(grade='42', subject='chemistry')
        self.assertFalse(response.context['shelves']['filtered'])
        self.assertIn('Без класса', self.shelf_titles(response))

    def test_source_page_unchanged(self):
        response = self.page(source=self.geo8.pk)
        self.assertContains(response, 'collection-source-card')
        self.assertIsNone(response.context['shelves'])
