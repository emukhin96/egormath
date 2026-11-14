"""Поиск задач по тексту условия: FULLTEXT-индекс MySQL с запасным icontains.

Каталог, подбор задач в листок и в самостоятельную ищут одной функцией
``text_search``. На MySQL запрос из обычных слов идёт в индекс
``problems_task_fulltext (text_plain, text_latex)`` (миграция
``0036_task_fulltext``) булевым режимом ``+слово*`` — каждое слово по
префиксу, все слова обязательны. Запросы, которые FULLTEXT не умеет,
и sqlite (тесты, разработка без MySQL) — прежний ``icontains`` по обоим
полям. Порядок выдачи задаёт вызывающий код (``-created_at, -pk``),
релевантность не используется.
"""
import re

from django.db import connections
from django.db.models import F, Func, Q, Value
from django.db.models.lookups import Lookup

# innodb_ft_min_token_size по умолчанию: слова короче в индексе нет,
# «+уг*» нашёл бы «угол», но не отдельное «уг» и не «круг» — такие запросы
# идут запасным путём (см. докстринг миграции 0036).
FULLTEXT_MIN_TOKEN = 3
SEARCH_FIELDS = ('text_plain', 'text_latex')
_WORD = re.compile(r'[^\W_]+')


class MatchAgainst(Lookup):
    """``MATCH(столбцы) AGAINST (%s IN BOOLEAN MODE)`` как условие WHERE.

    Именно ``Lookup``, а не ``Func`` с булевым полем: на MySQL Django
    дописывает к небулевым условиям ``= 1``, а ``MATCH`` возвращает
    релевантность, не 0/1.
    """
    lookup_name = 'match_against'
    prepare_rhs = False

    def __init__(self, columns, query):
        super().__init__(Func(*(F(c) for c in columns), function='MATCH'),
                         Value(query))

    def as_sql(self, compiler, connection):
        lhs_sql, lhs_params = self.process_lhs(compiler, connection)
        rhs_sql, rhs_params = self.process_rhs(compiler, connection)
        return ('%s AGAINST (%s IN BOOLEAN MODE)' % (lhs_sql, rhs_sql),
                (*lhs_params, *rhs_params))


def fulltext_query(q):
    """Строка булевого режима для запроса ``q`` или ``None``, если запрос
    FULLTEXT не умеет и нужен ``icontains``: пустой, со словом короче
    ``FULLTEXT_MIN_TOKEN``, с любым символом кроме букв и цифр (``\\sqrt``,
    ``x^2``, ``a-b``, запятые)."""
    words = q.split()
    if not words:
        return None
    for word in words:
        if len(word) < FULLTEXT_MIN_TOKEN or not _WORD.fullmatch(word):
            return None
    return ' '.join('+%s*' % word for word in words)


def uses_fulltext(tasks, q):
    """Пойдёт ли запрос ``q`` по queryset ``tasks`` в FULLTEXT-индекс."""
    return (connections[tasks.db].vendor == 'mysql'
            and fulltext_query(q) is not None)


def text_search(tasks, q, *, fulltext=None):
    """Задачи из ``tasks``, в условии которых есть ``q``.

    ``fulltext=False`` принудительно ведёт прежним ``icontains`` (сверка
    двух путей); ``None`` — по базе и запросу (``uses_fulltext``).
    """
    if fulltext is None:
        fulltext = uses_fulltext(tasks, q)
    if fulltext:
        return tasks.filter(MatchAgainst(SEARCH_FIELDS, fulltext_query(q)))
    condition = Q()
    for field in SEARCH_FIELDS:
        condition |= Q(**{field + '__icontains': q})
    return tasks.filter(condition)
