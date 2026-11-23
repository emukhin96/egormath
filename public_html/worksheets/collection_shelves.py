"""Страница «Подборки» полками по классам (вариант B, холст 23.11.2026).

Каждый задачник — карточка с обложкой, названием, авторами и разделом, без
счётчиков и тем. Полка — класс; книга на несколько классов стоит на каждой
своей полке. Фильтры ?grade= и ?subject= — бейджами. Полка занимает столько
колонок, сколько в ней книг (до четырёх), поэтому маленькие полки встают в
строку рядом. «Авторские листки» — единственное исключение: отдельный блок
наверху со ссылками на свои разделы.
"""
import re
from pathlib import PurePosixPath

from django.urls import reverse

from problems.models import Source
from problems.source_meta import SUBJECT_CHOICES, grade_label, guess_grades
from problems.templatetags.page_tools import query_url

from .corpus import SOURCE_TITLE as AUTHORED_SOURCE

GRADES = range(5, 12)
SHELF_COLUMNS = 4
SUBJECT_LABELS = dict(SUBJECT_CHOICES)
SUBJECT_ORDER = {code: index for index, (code, _label) in enumerate(SUBJECT_CHOICES)}


def cover_name(source):
    """Фамилия для обложки-заглушки: «Мерзляк», «Высоцкий», «Зив»."""
    for text in (source.short_title, source.author, source.title):
        for token in re.split(r'[\s,]+', text or ''):
            token = re.sub(r'[-–]?\d.*$', '', token.strip('.«»"'))
            if len(token) > 2 and token[0].isupper():
                return token
    return ''


def _grades_of(title):
    """Классы раздела авторских листков: «8 класс», «10–11 класс», «ОГЭ» → 9."""
    low, high = guess_grades(title)
    return set(range(low, high + 1)) if low else set()


def cover_url(source):
    """Ссылка на файл обложки или ''. ``?v=`` — хвост имени файла (хеш
    содержимого, problems/source_covers.py): перерисованная обложка
    обходит суточный кэш браузера."""
    if not source.cover:
        return ''
    version = PurePosixPath(source.cover.name).stem.rsplit('-', 1)[-1]
    return f"{reverse('source_cover', args=[source.pk])}?v={version}"


def _book(source):
    low, high = source.grade_from, source.grade_to or source.grade_from
    return {
        'source': source,
        'grades': set(range(low, high + 1)) if low else set(),
        'range': grade_label(low, high) if low and high != low else '',
        'cover_grade': grade_label(low, high),
        'cover_name': cover_name(source),
        'cover_url': cover_url(source),
        'subject_label': SUBJECT_LABELS.get(source.subject, ''),
    }


def _chips(params, name, choices, current):
    """Бейджи фильтра: «Все» и значения; повторный щелчок снимает выбор."""
    chips = [{'label': 'Все', 'url': query_url(params, {name: None}),
              'active': not current}]
    for value, label in choices:
        active = str(value) == current
        chips.append({'label': label, 'active': active,
                      'url': query_url(params, {name: None if active else value})})
    return chips


def shelves_context(catalog, params):
    """Контекст полок для ``collection_list`` без выбранного источника.

    ``catalog`` — ``collection_catalog(user)``; поля класса, раздела и
    обложки читаются из базы одним запросом (в кэше каталога источники
    могут быть до миграции полей)."""
    fresh = Source.objects.in_bulk([row['source'].pk for row in catalog])
    authored, books = None, []
    for row in catalog:
        source = fresh.get(row['source'].pk, row['source'])
        if source.title == AUTHORED_SOURCE:
            authored = {'source': source, 'sections': [
                {'collection': root['collection'],
                 'grades': _grades_of(root['collection'].catalog_title)}
                for root in row['roots']]}
        else:
            books.append(_book(source))
    grade = params.get('grade', '')
    grade = grade if grade.isdigit() and int(grade) in GRADES else ''
    subject = params.get('subject', '')
    subject = subject if subject in SUBJECT_LABELS else ''
    present_grades = sorted({g for book in books for g in book['grades'] if g in GRADES})
    present_subjects = [(code, label) for code, label in SUBJECT_CHOICES
                        if any(book['source'].subject == code for book in books)]
    pool = [book for book in books if not subject or book['source'].subject == subject]
    pool.sort(key=lambda book: (SUBJECT_ORDER.get(book['source'].subject, 99),
                                min(book['grades'] or {99}), book['source'].title))
    shelves = []
    for number in GRADES:
        if grade and number != int(grade):
            continue
        shelf_books = [book for book in pool if number in book['grades']]
        if shelf_books:
            shelves.append({'label': f'{number} класс', 'books': shelf_books})
    if not grade:
        loose = [book for book in pool if not book['grades'] & set(GRADES)]
        if loose:
            shelves.append({'label': 'Без класса', 'books': loose})
    for shelf in shelves:
        shelf['span'] = min(len(shelf['books']), SHELF_COLUMNS)
    if authored and grade:
        for section in authored['sections']:
            section['active'] = int(grade) in section['grades']
    shown = {book['source'].pk for shelf in shelves for book in shelf['books']}
    return {
        'authored': authored,
        'shelves': shelves,
        'grade_chips': _chips(params, 'grade', [(g, str(g)) for g in present_grades], grade),
        'subject_chips': _chips(params, 'subject', present_subjects, subject),
        'filtered': bool(grade or subject),
        'shown_total': len(shown),
        'books_total': len(books),
    }
