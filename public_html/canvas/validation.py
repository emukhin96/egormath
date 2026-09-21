"""Проверка JSON холста, пришедшего с клиента.

Всё, что сюда попало, потом рисуется в браузере другого человека, поэтому
принимаем только известные типы и ключи, целые координаты в разумном
диапазоне и цвета вида #rrggbb. Лишние ключи молча отбрасываются.

Элемент: {"id", "t", "c", "w", "p": [[x, y], ...], "g"?, "k"?, "l"?}
  t — тип, c — цвет, w — толщина, p — точки (логические единицы страницы
  1000×750), g — id группы, k — вид заготовки графика, l — подпись точки.
"""
import math
import re

from .models import CanvasPage

COORD_MIN, COORD_MAX = -300, 1200
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,16}$')
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# Сколько точек у каждого типа: (минимум, максимум)
POINT_COUNTS = {
    'path': (1, CanvasPage.MAX_POINTS),
    'hl': (1, CanvasPage.MAX_POINTS),
    'line': (2, 2),
    'dot': (1, 1),
    'circle': (2, 2),
    'rect': (2, 2),
    'tri': (3, 3),
    'para': (3, 3),
    'fn': (2, 2),
}
FN_KINDS = ('parabola', 'abs', 'sqrt', 'hyperbola')
BACKGROUNDS = {choice for choice, _ in CanvasPage.BG_CHOICES}
PLANE_CELLS = (25, 50)
PLANE_ORIGINS = ('center', 'bottom_left')


class CanvasValidationError(ValueError):
    pass


def _int(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanvasValidationError(f'{name}: ожидается число')
    if isinstance(value, float) and not math.isfinite(value):
        raise CanvasValidationError(f'{name}: ожидается конечное число')
    value = int(round(value))
    return value


def _point(raw):
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise CanvasValidationError('Точка должна быть парой чисел')
    x = _int(raw[0], 'x')
    y = _int(raw[1], 'y')
    if not (COORD_MIN <= x <= COORD_MAX and COORD_MIN <= y <= COORD_MAX):
        raise CanvasValidationError('Точка за пределами страницы')
    return [x, y]


def validate_element(raw):
    if not isinstance(raw, dict):
        raise CanvasValidationError('Элемент должен быть объектом')
    kind = raw.get('t')
    if not isinstance(kind, str) or kind not in POINT_COUNTS:
        raise CanvasValidationError(f'Неизвестный тип элемента: {kind!r}')
    element_id = raw.get('id')
    if not isinstance(element_id, str) or not ID_RE.match(element_id):
        raise CanvasValidationError('Некорректный id элемента')
    color = raw.get('c', '#111827')
    if not isinstance(color, str) or not COLOR_RE.match(color):
        raise CanvasValidationError('Цвет должен быть вида #rrggbb')
    width = _int(raw.get('w', 2), 'w')
    if not 1 <= width <= 60:
        raise CanvasValidationError('Толщина вне диапазона 1–60')
    points = raw.get('p')
    if not isinstance(points, list):
        raise CanvasValidationError('Нет списка точек')
    low, high = POINT_COUNTS[kind]
    if not low <= len(points) <= high:
        raise CanvasValidationError(f'У элемента {kind} должно быть от {low} до {high} точек')
    element = {
        'id': element_id, 't': kind, 'c': color.lower(), 'w': width,
        'p': [_point(point) for point in points],
    }
    group = raw.get('g')
    if group is not None:
        if not isinstance(group, str) or not ID_RE.match(group):
            raise CanvasValidationError('Некорректный id группы')
        element['g'] = group
    if kind == 'fn':
        fn_kind = raw.get('k')
        if fn_kind not in FN_KINDS:
            raise CanvasValidationError('Неизвестный вид графика')
        element['k'] = fn_kind
    if kind == 'dot' and raw.get('l'):
        element['l'] = True
    return element


def validate_elements(raw):
    if not isinstance(raw, list):
        raise CanvasValidationError('Слой должен быть списком элементов')
    if len(raw) > CanvasPage.MAX_ELEMENTS:
        raise CanvasValidationError(
            f'Слишком много элементов на странице (не больше {CanvasPage.MAX_ELEMENTS})')
    elements = [validate_element(item) for item in raw]
    ids = [element['id'] for element in elements]
    if len(ids) != len(set(ids)):
        raise CanvasValidationError('Повторяющиеся id элементов')
    return elements


def validate_background(background, options):
    if not isinstance(background, str) or background not in BACKGROUNDS:
        raise CanvasValidationError('Неизвестный фон')
    options = options if isinstance(options, dict) else {}
    if 'square' in options and not isinstance(options['square'], bool):
        raise CanvasValidationError('Некорректный формат страницы')
    clean = {}
    if background == CanvasPage.BG_PLANE:
        options = options if isinstance(options, dict) else {}
        # Без cell приходят только старые страницы 1000×750 — клиент рисует их
        # с мелкой клеткой и сменить её не даёт; новые страницы присылают 50 сами.
        cell = options.get('cell', PLANE_CELLS[0])
        if cell not in PLANE_CELLS:
            raise CanvasValidationError('Недопустимый размер клетки')
        origin = options.get('origin', PLANE_ORIGINS[0])
        if origin not in PLANE_ORIGINS:
            raise CanvasValidationError('Недопустимое положение начала координат')
        clean = {'cell': cell, 'origin': origin}
    if options.get('square'):
        clean['square'] = True
    return background, clean
