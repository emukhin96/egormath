"""Классы и раздел источника — для полок страницы «Подборки».

Поля ``Source.grade_from``/``grade_to``/``subject`` заполняются миграцией
по названию (``guess_grades``, ``guess_subject``), а где название молчит
(«Зив-8», «Шабунин 10–11») — по темам задач источника; дальше их правит
редактор в админке. Функции чистые: их зовёт и миграция, и подсветка
разделов авторских листков («8 класс», «ОГЭ»).
"""
import re

SUBJECT_CHOICES = [
    ('math', 'Математика'),
    ('algebra', 'Алгебра'),
    ('geometry', 'Геометрия'),
    ('statistics', 'Статистика'),
    ('exams', 'Экзамены'),
]

# Порядок важен: «Стереометрия ЕГЭ» — геометрия, «Математика. Алгебра…» —
# алгебра, «Математика — абитуриенту» — экзамены.
_SUBJECT_PATTERNS = [
    ('statistics', r'вероятност|статистик|комбинатор'),
    ('geometry', r'геометр|стереометр|планиметр|многогранник'),
    ('exams', r'\bЕГЭ\b|\bОГЭ\b|ФИПИ|абитуриент|вступительн'),
    ('algebra', r'алгебр|неравенств|анализ|уравнени'),
    ('math', r'математик'),
]

# Корни рубрикатора → раздел (если название источника раздела не выдаёт)
TOPIC_ROOT_SUBJECTS = {
    'ARI': 'math', 'ALG': 'algebra', 'GEO': 'geometry',
    'STA': 'statistics', 'COM': 'statistics',
}

MIN_GRADE, MAX_GRADE = 1, 11


def guess_subject(*texts):
    """Раздел по названию и автору или ''."""
    text = ' '.join(filter(None, texts))
    for code, pattern in _SUBJECT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return ''


def _grade(value):
    number = int(value)
    return number if MIN_GRADE <= number <= MAX_GRADE else None


def guess_grades(*texts):
    """``(от, до)`` классов по названию или ``(None, None)``:
    «8–9 классы», «Шабунин 10-11», «7 класс», «Зив-8», «ОГЭ» → 9, «ЕГЭ» → 11."""
    text = ' '.join(filter(None, texts))
    for match in re.finditer(r'(?<!\d)(\d{1,2})\s*[–—-]\s*(\d{1,2})(?!\d)', text):
        low, high = _grade(match.group(1)), _grade(match.group(2))
        if low and high and low < high:
            return low, high
    for pattern in (r'(?<!\d)(\d{1,2})\s*класс', r'[-–](\d{1,2})(?!\d)'):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            grade = _grade(match.group(1))
            if grade:
                return grade, grade
    if re.search(r'\bОГЭ\b', text):
        return 9, 9
    if re.search(r'\bЕГЭ\b|абитуриент|вступительн', text, re.IGNORECASE):
        return 11, 11
    return None, None


def grade_label(low, high):
    """«8», «8–9» или ''."""
    if not low:
        return ''
    return str(low) if not high or high == low else f'{low}–{high}'
