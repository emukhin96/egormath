"""FULLTEXT-индекс для поиска задач по тексту (аудит быстродействия, круг 3).

Индекс только для MySQL: ``problems_task_fulltext (text_plain, text_latex)``
со стандартным парсером InnoDB. На sqlite (тесты, разработка без MySQL)
операция ничего не делает — там поиск идёт прежним ``icontains``
(``problems/search.py``).

Выбор парсера — замер на копии прода (29,8 тыс. задач, 14.11.2026, MySQL
9.4 локально; прод — MySQL 8.0 с настройками по умолчанию):

* стандартный парсер: ``COUNT(*)`` + первая страница 0,2–20 мс против
  50–70 мс + до 80 мс у ``LIKE '%…%'``; индекс строится 2,5 с;
* ``WITH PARSER ngram`` (``ngram_token_size=2``): 10–75 мс на частых словах
  («уравнение», «Найдите») — почти как ``LIKE``, индекс строится 6 с и
  вдвое больше. Даёт поиск по подстроке внутри слова, но выигрыша по
  времени почти нет — отвергнут.

Стандартный парсер индексирует слова от ``innodb_ft_min_token_size``
(по умолчанию 3) символов и ищет по префиксу слова (``+квадрат*`` находит
«квадрата», «квадратный», но не «биквадратное»). Запросы с словом короче
трёх символов, с не буквенно-цифровыми символами (``\\sqrt``, ``x^2``)
и по ``#id`` в индекс не ходят — ``problems.search.fulltext_query``.
``text_latex`` в индексе ради слов вроде «sin» и «frac», которые в
``text_plain`` стёрты ``strip_latex``: раньше их находил ``LIKE`` по
``text_latex``.

Параметры сервера ``innodb_ft_min_token_size`` и список стоп-слов —
по умолчанию (``deploy/vps/mysql.cnf`` их не меняет); при изменении индекс
нужно пересобрать.
"""
from django.db import migrations

INDEX_NAME = 'problems_task_fulltext'


def add_fulltext(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    table = apps.get_model('problems', 'Task')._meta.db_table
    quote = schema_editor.quote_name
    schema_editor.execute(
        'ALTER TABLE %s ADD FULLTEXT INDEX %s (%s, %s)'
        % (quote(table), quote(INDEX_NAME), quote('text_plain'), quote('text_latex')))


def drop_fulltext(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    table = apps.get_model('problems', 'Task')._meta.db_table
    quote = schema_editor.quote_name
    schema_editor.execute(
        'ALTER TABLE %s DROP INDEX %s' % (quote(table), quote(INDEX_NAME)))


class Migration(migrations.Migration):

    # DDL на MySQL не откатывается — вне транзакции миграции
    atomic = False

    dependencies = [
        ('problems', '0035_facetvalue_parent'),
    ]

    operations = [
        migrations.RunPython(add_fulltext, drop_fulltext),
    ]
