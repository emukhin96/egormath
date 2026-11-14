"""Поиск задач по тексту: FULLTEXT на MySQL и запасной icontains (search.py).

Путь через индекс выполняется только на MySQL — тесты сравнения двух путей
пропускаются на sqlite и запускаются на копии прода:
``DB_ENGINE=mysql DB_NAME=egormath_shot … manage.py test problems.test_search``.
"""
from unittest import skipUnless

from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from .models import Task
from .search import fulltext_query, text_search, uses_fulltext
from .tests import make_teacher
from .views import filter_tasks

ON_MYSQL = connection.vendor == 'mysql'


def make_search_tasks(teacher):
    """Задачи для сверки путей поиска; ключ — смысл условия."""
    texts = {
        'square': 'Найдите площадь квадрата со стороной 4.',
        'biquadratic': 'Решите биквадратное уравнение $x^4-5x^2+4=0$.',
        'sqrt': 'Решите уравнение $\\sqrt{x+1}=3$.',
        'triangle': 'Найдите площадь треугольника с катетами 3 и 4.',
        # Оба слова, но не рядом: подстрока «площадь треугольника» не найдётся
        'triangle_area': 'Периметр треугольника 12, а площадь 6.',
        # Строчные буквы: LIKE в sqlite сворачивает регистр только у ASCII
        'current': 'В цепи ток равен 2 А.',
        'flow': 'Измерьте поток воды через трубу.',
        'sin': 'Вычислите $\\sin 30^\\circ$.',
        'yo': 'Ещё одна задача про ёж и ежей.',
    }
    return {key: Task.new_for(teacher, text_latex=text)
            for key, text in texts.items()}


class FulltextQueryTests(SimpleTestCase):
    """Строка булевого режима: когда FULLTEXT годится, а когда нет."""

    def test_words_become_required_prefixes(self):
        self.assertEqual(fulltext_query('квадрат'), '+квадрат*')
        self.assertEqual(fulltext_query('  Площадь   треугольника '),
                         '+Площадь* +треугольника*')
        self.assertEqual(fulltext_query('ток'), '+ток*')
        self.assertEqual(fulltext_query('зелёный'), '+зелёный*')
        self.assertEqual(fulltext_query('x2y'), '+x2y*')

    def test_short_words_fall_back(self):
        # Слова короче innodb_ft_min_token_size в индексе нет
        self.assertIsNone(fulltext_query('уг'))
        self.assertIsNone(fulltext_query('угол 30'))
        self.assertIsNone(fulltext_query('а'))

    def test_special_characters_fall_back(self):
        for q in ('\\sqrt', '\\frac', 'x^2', 'a-b', 'x_1', 'sin(x)', 'точка,',
                  '+квадрат*', '"квадрат"', '2,5 м'):
            with self.subTest(q=q):
                self.assertIsNone(fulltext_query(q))

    def test_empty_falls_back(self):
        self.assertIsNone(fulltext_query(''))
        self.assertIsNone(fulltext_query('   '))


class TextSearchTests(TestCase):
    """Выдача на подготовленных задачах: #id, запасной путь, оба пути."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_teacher()
        cls.tasks = make_search_tasks(cls.teacher)

    def pks(self, qs):
        return set(qs.values_list('pk', flat=True))

    def expect(self, *keys):
        return {self.tasks[k].pk for k in keys}

    def search(self, q, **kwargs):
        return self.pks(text_search(Task.objects.all(), q, **kwargs))

    def test_id_lookup_bypasses_text_search(self):
        task = self.tasks['square']
        for q in ('#%d' % task.pk, str(task.pk)):
            params = {'q': q}
            self.assertEqual(self.pks(filter_tasks(params, self.teacher)), {task.pk})

    def test_icontains_path_is_substring_search(self):
        self.assertEqual(self.search('квадрат', fulltext=False),
                         self.expect('square', 'biquadratic'))
        self.assertEqual(self.search('ток', fulltext=False),
                         self.expect('current', 'flow'))
        self.assertEqual(self.search('\\sqrt', fulltext=False), self.expect('sqrt'))
        self.assertEqual(self.search('sin', fulltext=False), self.expect('sin'))
        self.assertEqual(self.search('площадь треугольника', fulltext=False),
                         self.expect('triangle'))

    def test_special_queries_take_icontains_path_everywhere(self):
        for q in ('\\sqrt', 'x^2', 'уг', 'угол 30'):
            with self.subTest(q=q):
                self.assertFalse(uses_fulltext(Task.objects.all(), q))
        self.assertEqual(self.search('\\sqrt'), self.expect('sqrt'))
        self.assertEqual(self.search('уг'), self.expect('triangle', 'triangle_area'))



class TextSearchViewTests(TransactionTestCase):
    """Каталог и ``filter_tasks`` ищут через ``text_search`` — на обоих
    бэкендах; вне транзакции, иначе на MySQL FULLTEXT не увидит задачи."""

    def setUp(self):
        self.teacher = make_teacher()
        self.tasks = make_search_tasks(self.teacher)

    pks = TextSearchTests.pks
    expect = TextSearchTests.expect

    def test_catalog_and_filter_tasks_use_text_search(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('task_list'), {'q': 'тетраэдр'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page'].object_list), 0)
        response = self.client.get(reverse('task_list'), {'q': 'треугольника'})
        self.assertEqual(response.status_code, 200)
        found = {t.pk for t in response.context['page'].object_list}
        self.assertIn(self.tasks['triangle'].pk, found)
        self.assertEqual(self.pks(filter_tasks({'q': 'поток'}, self.teacher)),
                         self.expect('flow'))


@skipUnless(ON_MYSQL, 'FULLTEXT-индекс есть только на MySQL')
class FulltextMysqlTests(TransactionTestCase):
    """Путь через индекс против icontains. InnoDB добавляет документы в
    FULLTEXT-индекс только при фиксации транзакции, поэтому не ``TestCase``
    (его тесты идут внутри незафиксированной транзакции и ничего не нашли бы)."""

    def setUp(self):
        self.teacher = make_teacher()
        self.tasks = make_search_tasks(self.teacher)

    pks = TextSearchTests.pks
    expect = TextSearchTests.expect
    search = TextSearchTests.search

    def test_fulltext_path_matches_icontains_on_whole_words(self):
        for q in ('площадь', 'уравнение', 'Решите', 'треугольника', 'зад', 'sin'):
            with self.subTest(q=q):
                self.assertTrue(uses_fulltext(Task.objects.all(), q))
                self.assertEqual(self.search(q), self.search(q, fulltext=False))

    def test_fulltext_path_documented_differences(self):
        # Префикс слова, а не подстрока: «биквадратное» не находится
        self.assertEqual(self.search('квадрат'), self.expect('square'))
        self.assertEqual(self.search('ток'), self.expect('current'))
        # Все слова обязательны, но в любом месте условия
        self.assertEqual(self.search('площадь треугольника'),
                         self.expect('triangle', 'triangle_area'))
        # Регистр и ё/е сворачиваются, как и у icontains на MySQL
        self.assertEqual(self.search('КВАДРАТА'), self.search('КВАДРАТА', fulltext=False))
        self.assertEqual(self.search('КВАДРАТА'), self.expect('square'))
        self.assertEqual(self.search('еще'), self.search('ещё', fulltext=False))
