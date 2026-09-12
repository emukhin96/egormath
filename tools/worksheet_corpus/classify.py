"""Темы и экзаменационные метки по имени файла и заголовку."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .paths import classify_report_path
from .store import iter_draft_paths, load_json, save_draft

# Короткие ярлыки листков → код рубрикатора. Не создаём новые темы.
WORKSHEET_ALIASES = {
    'процент от числа': 'ARI.04.04',
    'проценты': 'ARI.04.04',
    'процент': 'ARI.04.04',
    'нахождение процента от числа': 'ARI.04.04',
    'дроби': 'ARI.03.04',
    'обыкновенные дроби': 'ARI.03.01',
    'десятичные дроби': 'ARI.03.05',
    'алгебраические дроби': 'ALG.02.14',
    'делимость': 'ARI.02.01',
    'взаимно простые числа': 'ARI.02.03',
    'признаки делимости': 'ARI.02.01',
    'буквенные выражения': 'ALG.02.01',
    'многочлены': 'ALG.02.02',
    'одночлены': 'ALG.02.11',
    'формулы сокращенного умножения': 'ALG.02.04',
    'формулы сокращённого умножения': 'ALG.02.04',
    'разложение на множители': 'ALG.02.05',
    'степень': 'ALG.02.16',
    'степень и одночлен': 'ALG.02.11',
    'линейные уравнения': 'ALG.03.01',
    'уравнения': 'ALG.03',
    'квадратные уравнения': 'ALG.03.03',
    'неравенства': 'ALG.04',
    'системы уравнений': 'ALG.03.11',
    'модуль': 'ARI.05.04',
    'пропорция': 'ARI.04.02',
    'отношения': 'ARI.04.01',
    'пропорциональность': 'ARI.04.03',
    'текстовые задачи': 'ALG.09',
    'теория вероятностей': 'STA',
    'комбинаторика': 'STA',
    'прогрессии': 'ALG.06',
    'арифметическая прогрессия': 'ALG.06.02',
    'геометрическая прогрессия': 'ALG.06.03',
    'функции': 'ALG.05',
    'квадратичная функция': 'ALG.05.04',
    'графики': 'ALG.05.03',
    'производная': 'ALG.07',
    'тригонометрия': 'ALG.02.18',
    'тригонометрические уравнения': 'ALG.03.10',
    'простейшие тригонометрические уравнения': 'ALG.03.10',
    'логарифмы': 'ALG.02.08',
    'показательные': 'ALG.03.08',
    'параметр': 'ALG.08.01',
    'уравнения с параметром': 'ALG.08.01',
    'параллельные прямые': 'GEO.01.04',
    'треугольники': 'GEO.02',
    'окружность': 'GEO.04',
    'четырехугольники': 'GEO.03',
    'четырёхугольники': 'GEO.03',
    'параллелограмм': 'GEO.03.01',
    'трапеция': 'GEO.03.02',
    'подобие': 'GEO.02.06',
    'теорема пифагора': 'GEO.02.05',
    'площади': 'GEO.03.07',
    'векторы': 'GEO.06.04',
    'координаты': 'GEO.06.01',
    'стереометрия': 'GEO.08',
    'объемы': 'GEO.08',
    'объёмы': 'GEO.08',
    'ортоцентр треугольника': 'GEO.02.09',
    'теорема синусов': 'GEO.02.07',
    'теорема косинусов': 'GEO.02.07',
    'принцип дирихле': 'ARI.02.08',
    'логика': 'ARI.01.06',
    'отрезки': 'GEO.01.01',
    'натуральные числа': 'ARI.01.01',
    'геометрическая вероятность': 'STA.03.05',
    'геометрическая вероятность. дуга': 'STA.03.05',
    'сложные проценты': 'ARI.04.07',
    'смеси и сплавы': 'ARI.04.06',
    'вклады и кредиты': 'ARI.04.07',
    'задачи о вкладах и кредитах': 'ARI.04.07',
    'метод рационализации': 'ALG.02.08',
    'логарифмические неравенства': 'ALG.04.08',
    'простейшие логарифмические уравнения': 'ALG.03.09',
    'логарифмические уравнения': 'ALG.03.09',
    'основные понятия стереометрии': 'GEO.08.01',
    'взаимное расположение прямых в пространстве': 'GEO.08.02',
    'угол между прямой и плоскостью': 'GEO.08.04',
    'планиметрия': 'GEO',
    'прямоугольный треугольник': 'GEO.02.05',
    'теорема чевы': 'GEO.02.10',
    'теорема менелая': 'GEO.02.10',
    'теоремы менелая и чевы': 'GEO.02.10',
    'теорема синусов': 'GEO.02.07',
    'средняя линия': 'GEO.02.03',
    'средняя линия треугольника': 'GEO.02.03',
    'пропорциональные отрезки': 'GEO.02.06',
    'пропорциональные отрезки в треугольнике': 'GEO.02.06',
    'выделение полного квадрата': 'ALG.02.15',
    'дискриминант': 'ALG.03.03',
    'сложение алгебраических дробей': 'ALG.02.14',
    'алгебраические выражения': 'ALG.02.01',
    'начальные геометрические сведения': 'GEO.01',
    'многоугольники': 'GEO.03',
    'график квадратичной функции': 'ALG.05.04',
    'квадратичная функция: общий случай': 'ALG.05.04',
    'линейные неравенства': 'ALG.04.02',
    'метод интервалов': 'ALG.04.04',
    'метод координат': 'GEO.06.01',
    'векторы. основные понятия': 'GEO.06.04',
    'скалярное произведение векторов': 'GEO.06.05',
    'координатно-векторный метод': 'GEO.06.06',
    'арифметический квадратный корень': 'ARI.05.01',
    'площадь параллелограмма и треугольника': 'GEO.03.07',
    'противоположные события': 'STA.03.04',
    'диаграммы эйлера': 'STA.04.01',
    'введение в комбинаторику': 'COM',
    'введение в логику': 'ALG.01.04',
    'пропорция. масштаб': 'ARI.04.02',
    'признаки делимости': 'ARI.02.01',
    'цепочки вычислений': 'ARI.01.05',
    'иррациональные уравнения': 'ALG.03.07',
    'показательные уравнения': 'ALG.03.08',
    'рациональные и иррациональные уравнения': 'ALG.03',
    'текстовые задачи на делимость': 'ARI.02.08',
    'углы и прямые': 'GEO.01',
    'смеси и сплавы': 'ARI.04.06',
    'геометрия': 'GEO',
    'алгебра': 'ALG',
    'повторение степеней': 'ALG.02.16',
    'преобразование выражений': 'ALG.02.01',
    'переменные и повторение': 'ALG.02.01',
    'простейшие уравнения': 'ALG.03.01',
    'решение уравнений': 'ALG.03',
    'решение уравнений. координаты на плоскости': 'ALG.03',
    'уравнения с модулем': 'ALG.03.06',
    'решение уравнений с модулем': 'ALG.03.06',
    'действия с дробями': 'ARI.03.04',
    'понятие отношения': 'ARI.04.01',
    'проценты и доли': 'ARI.04.04',
    'проценты. части и отношения': 'ARI.04.04',
    'задачи на части': 'ARI.04.06',
    'деление в данном отношении': 'ARI.04.06',
    'нахождение части от числа': 'ARI.04.04',
    'нахождение целого по его части': 'ARI.04.04',
    'задачи прикладного содержания': 'ALG.09.07',
    'объёмы многогранников и тел вращения': 'GEO.09.06',
    'расположение корней квадратого уравнения': 'ALG.08.04',
    'расположение корней квадратного трёхчлена относительно заданных точек': 'ALG.08.04',
    'уравнения в целых числах': 'ARI.02.07',
    'расчёт расстояний': 'GEO.08.04',
    'делимость. взаимно простые числа': 'ARI.02.03',
    'делимость натуральных чисел': 'ARI.02.01',
    'логика отрицаний': 'ALG.01.04',
    'умножение многочлена на многочлен': 'ALG.02.02',
    'прямоугольные треугольники': 'GEO.02.05',
    'сумма углов треугольника': 'GEO.02.01',
    'множества и действия с ними': 'ALG.01.02',
    'степень с натуральным показателем': 'ARI.05.03',
    'линейная функция и её график': 'ALG.05.04',
    'график функции. прямая пропорциональность': 'ALG.05.15',
    'вычисление значений функции по формуле': 'ALG.05.01',
    'описательная статистика': 'STA.02',
    'четырехугольники. зачётные задания': 'GEO.03',
    'параллелограмм, прямоугольник, ромб': 'GEO.03.01',
    'соотношения в прямоугольном треугольнике': 'GEO.02.05',
    'касательная к окружности': 'GEO.04.03',
    'квадратные уравнения с параметрами': 'ALG.08.01',
    'многоугольники': 'GEO.03.04',
    'формулы планиметрии': 'GEO',
    'сравнение квадратных корней с целыми числами': 'ARI.05.01',
    'действия с квадратными корнями': 'ARI.05.01',
    'кусочно заданные функции': 'ALG.05.08',
    'функция y=x^2 и её график': 'ALG.05.06',
    'сравнение выражений с корнями': 'ARI.05.01',
    'системы и совокупности неравенств': 'ALG.04.02',
    'теорема виета и её применение': 'ALG.03.03',
    'теорема фалеса': 'GEO.02.06',
    'теорема вариньона': 'GEO.03.03',
    'вписанный четырёхугольник': 'GEO.03.06',
    'угол между касательной и хордой': 'GEO.04.03',
    'прямоугольник, ромб, квадрат': 'GEO.03.01',
    'случайный выбор': 'STA.03.03',
    'композиция функций. обратные функции': 'ALG.05.12',
    'применение свойств функций': 'ALG.05.02',
    'свойства функций': 'ALG.05.02',
    'теорема безу. схема горнера': 'ALG.02.09',
    'метод замены переменной': 'ALG.03.04',
    'графический метод решения неравенств': 'ALG.05.13',
    'графический метод решения систем уравнений': 'ALG.05.13',
    'системы дробно рациональных неравенств': 'ALG.04.04',
    'задачи на движение': 'ALG.09.02',
    'теорема косинусов. решение треугольников': 'GEO.02.07',
    'медианы, высоты и биссектрисы треугольника': 'GEO.02.03',
    'метод координат. введение': 'GEO.06.01',
    'уравнения прямой': 'GEO.06.02',
    'предел последовательности': 'ALG.07.01',
    'вычисление пределов последовательностей': 'ALG.07.01',
    'правило умножения. перестановки': 'COM.01.03',
    'треугольник паскаля': 'COM.02.01',
    'комбинаторное правило умножения': 'COM.01.03',
    'сочетания и число сочетаний': 'COM.01.06',
    '10. вероятность': 'STA.03.03',
    'решение треугольников': 'GEO.02.07',
    'координатно векторный метод': 'GEO.06.06',
    'пропорциональные отрезки в прямоугольном треугольнике': 'GEO.02.06',
    'пропорциональные отрезки в окружности': 'GEO.04.03',
    'пропорциональные отрезки. обобщение': 'GEO.02.06',
    'элементы равностороннего треугольника': 'GEO.02.04',
    'степень с целым отрицательным показателем': 'ALG.02.16',
    'преобразования графиков функций': 'ALG.05.03',
    'простейшая модель банковской системы': 'ALG.09.06',
    'нахождение медиан, биссектрис и высот треугольника': 'GEO.02.03',
    'отрезки, пересекающиеся внутри угла': 'GEO.02.10',
    'применение теорем синусов и косинусов': 'GEO.02.07',
    'квадратные уравнения и уравнения, сводящиеся к ним': 'ALG.03.04',
    'числа, алгебраические выражения и неравенства': 'ALG.02',
    'измерение отрезков и углов': 'GEO.01.02',
    'расстояние от точки до прямой': 'GEO.01.05',
    'введение в логику': 'ALG.01.04',
    'выражения с переменными': 'ALG.01.01',
    'допустимые значения переменных': 'ALG.01.01',
    'числовые выражения': 'ARI.01.06',
    'подобие фигур': 'GEO.02.06',
    'окружность. зачётные задания': 'GEO.04',
    'четырерёхугольники': 'GEO.03',
    'четырехугольники': 'GEO.03',
    'функциональные методы решения': 'ALG.08.01',
    'графические методы решения задач с параметром': 'ALG.08.03',
    'взаимное расположение окружностей и многоугольников': 'GEO.04.05',
    'примение суммы углов треугольника': 'GEO.02.01',
    'площади (повторение)': 'GEO.03.07',
    'решение квадратных уравнений': 'ALG.03.03',
    'решение задач с помощью формул сокращённого умножения': 'ALG.02.03',
    'метод разложения на множители': 'ALG.02.04',
    'дополнительные построения в трапеции': 'GEO.03.02',
    'элементы равностороннего и прямоугольного треугольников': 'GEO.02.04',
    'корни. задание на замену': 'ARI.05.01',
    'функции и системы линейных уравнений': 'ALG.03.02',
    'анализ геометрических высказываний': 'GEO',
    'подготовка к итоговой работе по теории вероятностей': 'STA.03',
    'замена. алгебра': 'ALG',
    'квадратные уравнения': 'ALG.03.03',
    'на нахождение целого и частей': 'ARI.04.04',
    'на части': 'ARI.04.06',
    'вопросы к экзамену по геометрии': 'GEO',
    'требования к оформлению задач по геометрии': 'GEO',
    'образец решения задачи по геометрии': 'GEO',
    'действия с натуральными числами': 'ARI.01.05',
}

_FILENAME_HINTS = [
    (re.compile(r'(?i)prots|percent|процент'), 'ARI.04.04'),
    (re.compile(r'(?i)delim|делим'), 'ARI.02.01'),
    (re.compile(r'(?i)bukv|букв'), 'ALG.02.01'),
    (re.compile(r'(?i)fsu|factor|сократ'), 'ALG.02.04'),
    (re.compile(r'(?i)mnogochl|многочл'), 'ALG.02.02'),
    (re.compile(r'(?i)odnochl|одночл'), 'ALG.02.11'),
    (re.compile(r'(?i)kv_ur|kvadr'), 'ALG.03.03'),
    (re.compile(r'(?i)linear|линей'), 'ALG.03.01'),
    (re.compile(r'(?i)nerav|неравен'), 'ALG.04'),
    (re.compile(r'(?i)teorver|veroyat|вероят'), 'STA'),
    (re.compile(r'(?i)progr'), 'ALG.06'),
    (re.compile(r'(?i)trig|sincos'), 'ALG.02.18'),
    (re.compile(r'(?i)log'), 'ALG.02.08'),
    (re.compile(r'(?i)param'), 'ALG.08.01'),
    (re.compile(r'(?i)okr|окруж'), 'GEO.04'),
    (re.compile(r'(?i)podob'), 'GEO.02.06'),
    (re.compile(r'(?i)pifagor'), 'GEO.02.05'),
    (re.compile(r'(?i)parall'), 'GEO.01.04'),
    (re.compile(r'(?i)trap'), 'GEO.03.02'),
    (re.compile(r'(?i)plosch|площад'), 'GEO.03.07'),
    (re.compile(r'(?i)vec|вектор'), 'GEO.06.04'),
    (re.compile(r'(?i)stereom|объем|объём'), 'GEO.08'),
    (re.compile(r'(?i)drobi|дроб'), 'ARI.03.04'),
    (re.compile(r'(?i)module|модул'), 'ARI.05.04'),
    (re.compile(r'(?i)prop'), 'ARI.04.02'),
    (re.compile(r'(?i)dirich'), 'ARI.02.08'),
    (re.compile(r'(?i)otrez'), 'GEO.01'),
    (re.compile(r'(?i)menelay|cheva|чевы|менел'), 'GEO.02.10'),
    (re.compile(r'(?i)geom[_ ]?ver|geomver'), 'STA.03.05'),
    (re.compile(r'(?i)complexprots|сложных?\s+процент'), 'ARI.04.07'),
    (re.compile(r'(?i)srlin|sr_lin|средн[_ ]?лин'), 'GEO.02.03'),
    (re.compile(r'(?i)vydel_poln|полн[_ ]?кв'), 'ALG.02.15'),
    (re.compile(r'(?i)drobi_slozh'), 'ALG.02.14'),
    (re.compile(r'(?i)vzaim[_-]?prost'), 'ARI.02.03'),
    (re.compile(r'(?i)uravn|ur-mod|\bur\b'), 'ALG.03'),
    (re.compile(r'(?i)otn1|otnos'), 'ARI.04.01'),
    (re.compile(r'(?i)vieta'), 'ALG.03.03'),
    (re.compile(r'(?i)bezu|gorner'), 'ALG.02.09'),
    (re.compile(r'(?i)pascal'), 'COM.02.01'),
    (re.compile(r'(?i)sochet|perest|komb'), 'COM.01'),
    (re.compile(r'(?i)\blim\b|предел'), 'ALG.07.01'),
    (re.compile(r'(?i)fales|фалес'), 'GEO.02.06'),
    (re.compile(r'(?i)kasat'), 'GEO.04.03'),
    (re.compile(r'(?i)parab|kv_f'), 'ALG.05.06'),
    (re.compile(r'(?i)ege06'), 'ALG.03'),
    (re.compile(r'(?i)ege09'), 'ALG.09'),
    (re.compile(r'(?i)ege14|volumes'), 'GEO.09.06'),
    (re.compile(r'(?i)ege18|param'), 'ALG.08.01'),
    (re.compile(r'(?i)ege19|integers'), 'ARI.02.07'),
    (re.compile(r'(?i)oge-10(?!\d)'), 'STA.03.03'),
    (re.compile(r'(?i)oge-2[345]'), 'GEO'),
    (re.compile(r'(?i)tcos|t_sin|resh_treug|reshtreug'), 'GEO.02.07'),
    (re.compile(r'(?i)med_vys|biss'), 'GEO.02.03'),
    (re.compile(r'(?i)met_koord|ur_pr'), 'GEO.06.01'),
    (re.compile(r'(?i)scal_proizv'), 'GEO.06.05'),
    (re.compile(r'(?i)kvur|kv_ur|kv_kor'), 'ALG.03.03'),
    (re.compile(r'(?i)teorver'), 'STA.03'),
]

OGE_RE = re.compile(r'(?i)oge[-_ ](\d{1,2})(?:[^0-9]|$)')
EGE_BASE_RE = re.compile(r'(?i)ege[-_]?base[-_ ]?(\d{1,2})')
EGE_RE = re.compile(r'(?i)ege[-_ ](\d{1,2})(?:[^0-9]|$)')
EGE_STUCK_RE = re.compile(r'(?i)(?:^|[^a-z])ege(\d{1,2})(?:[^0-9]|$)')
ZADANIE_RE = re.compile(r'(?i)задани[ея]\s*(\d{1,2})')
MCKO_RE = re.compile(r'(?i)(?:^|[^a-zа-я])(?:mcko|мцко)(?:[^a-zа-я]|$)')
TASK_OGE_RE = re.compile(
    r'(?i)\\oge\b|(?:^|[^A-Za-zА-Яа-яЁё\\])ОГЭ\b')
TASK_EGE_RE = re.compile(
    r'(?i)\\ege\b|(?:^|[^A-Za-zА-Яа-яЁё\\])ЕГЭ\b')
TASK_FIPI_RE = re.compile(
    r'(?i)\\fipi\b|(?:^|[^A-Za-zА-Яа-яЁё\\])ФИПИ\b')


def _norm(text):
    text = str(text or '').replace('ё', 'е').replace('Ё', 'Е')
    text = re.sub(r'[«»"“”„()[\],:;—–-]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def _topic_catalog():
    """Код → имя из rubricator_data, без обращения к БД."""
    try:
        from problems.rubricator_data import BLOCKS
    except ImportError:
        return {}, {}
    by_code = {}
    by_name = {}
    for block_code, block_name, sections in BLOCKS:
        by_code[block_code] = block_name
        by_name[_norm(block_name)] = block_code
        for section_code, section_name, topics in sections:
            by_code[section_code] = section_name
            by_name[_norm(section_name)] = section_code
            for topic_code, topic_name in topics:
                by_code[topic_code] = topic_name
                by_name[_norm(topic_name)] = topic_code
    return by_code, by_name


def _merged_aliases():
    aliases = { _norm(k): v for k, v in WORKSHEET_ALIASES.items()}
    try:
        from problems.textbook_topics import TOPIC_ALIASES
        aliases.update(TOPIC_ALIASES)
    except Exception:
        pass
    return aliases


# Ниже этого барьера тему в черновик не пишем — только кандидаты на сверку.
TOPIC_ASSIGN_MIN = 0.92
_CONFIDENT_REASONS = frozenset({
    'exact-alias', 'exact-name', 'alias-contains',
})
_WEAK_ALIASES = frozenset({
    'уравнения', 'геометрия', 'алгебра', 'функции', 'неравенства',
    'повторение', 'процент', 'дроби', 'степень',
})


def topic_is_confident(candidate: dict | None) -> bool:
    """True, если кандидата можно ставить в topic_code без ручной сверки."""
    if not candidate:
        return False
    if candidate.get('score', 0) < TOPIC_ASSIGN_MIN:
        return False
    reason = candidate.get('reason')
    if reason in _CONFIDENT_REASONS:
        return True
    if reason == 'filename':
        # Имя файла годится, только если это не голый блок (STA/GEO/ALG).
        code = candidate.get('code') or ''
        return '.' in code and candidate.get('score', 0) >= 0.93
    return False


_TITLE_PREFIX_RE = re.compile(
    r'^(?:контрольная работа|самостоятельная работа|домашняя работа|'
    r'тренировочн\w+\s+вариант|тренировочная работа|зачёт|тест|'
    r'математический диктант|огэ|егэ|итоговая работа|'
    r'домашняя работа\.)'
    r'(?:\s*№?\s*\d+)?(?:\s*\(\d{4}\))?(?:\s*\(\d{2}\.\d{2}\.\d{4}\))?'
    r'[.\s:—–-]*',
    re.I)


def _title_variants(raw_label):
    variants = [raw_label]
    stripped = re.sub(r'^\d+[\.\)]?\s*', '', raw_label).strip()
    if stripped and stripped not in variants:
        variants.append(stripped)
    deco = _TITLE_PREFIX_RE.sub('', raw_label).strip(' .:—–-')
    deco = re.sub(r'\b20\d{2}\b', '', deco).strip(' .:—–-')
    if deco and deco not in variants:
        variants.append(deco)
    for piece in re.split(r'[.;/|]', deco or raw_label):
        piece = piece.strip(' .:—–-')
        if len(piece) >= 4 and piece not in variants:
            variants.append(piece)
    return variants


def suggest_topic(draft: dict) -> list[dict]:
    by_code, by_name = _topic_catalog()
    aliases = _merged_aliases()
    labels = []
    header = draft.get('header') or {}
    for raw in (
            draft.get('title'),
            header.get('title'),
            header.get('subtitle'),
            header.get('left'),
            Path_stem(draft.get('rel_path') or ''),
    ):
        label = _norm(raw)
        if label and label not in labels:
            labels.append(label)
    rubric_labels = []
    for el in draft.get('elements') or []:
        if el.get('kind') == 'rubric':
            label = _norm(el.get('rubric'))
            if label and label not in rubric_labels:
                rubric_labels.append(label)
    ranked = {}
    for raw_label in labels:
        variants = _title_variants(raw_label)
        for label in variants:
            code = aliases.get(label)
            if code and code in by_code:
                ranked[code] = {
                    'code': code, 'name': by_code[code],
                    'score': 1.0, 'reason': 'exact-alias',
                }
            if label in by_name:
                code = by_name[label]
                ranked[code] = {
                    'code': code, 'name': by_code.get(code, label),
                    'score': 1.0, 'reason': 'exact-name',
                }
            best_sub = None
            for alias, alias_code in aliases.items():
                if (len(alias) < 12 or alias_code not in by_code
                        or alias in _WEAK_ALIASES):
                    continue
                # Только «алиас внутри заголовка», не наоборот:
                # иначе «подготовка к итоговой работе» наследует
                # «…по теории вероятностей».
                if alias in label:
                    if best_sub is None or len(alias) > best_sub[0]:
                        best_sub = (len(alias), alias_code, alias)
            if best_sub:
                ranked.setdefault(best_sub[1], {
                    'code': best_sub[1],
                    'name': by_code[best_sub[1]],
                    'score': 0.96, 'reason': 'alias-contains',
                })
    # Рубрика — намёк, не тема всего листка (в «итоговой» их несколько).
    if not any(item['score'] >= 1.0 for item in ranked.values()):
        for raw_label in rubric_labels:
            for label in _title_variants(raw_label):
                code = aliases.get(label) or by_name.get(label)
                if code and code in by_code:
                    ranked.setdefault(code, {
                        'code': code, 'name': by_code[code],
                        'score': 0.90, 'reason': 'rubric',
                    })
    rel = draft.get('rel_path') or ''
    name = (draft.get('rel_path') or '').split('/')[-1]
    generic = {
        'самостоятельная работа', 'контрольная работа', 'домашняя работа',
        'тест', 'диагностическая работа', 'подготовка к аттестации',
        'подготовка к аттестационной работе', 'подготовка к итоговой аттестации',
        'подготовка к промежуточной аттестации', 'задание на замену',
        'тестовый файл', 'итоговая работа',
    }
    labels_are_generic = bool(labels) and all(
        _TITLE_PREFIX_RE.sub('', lab).strip() in generic
        or lab in generic for lab in labels)
    if labels_are_generic or not any(
            item['score'] == 1.0 for item in ranked.values()):
        for pattern, code in _FILENAME_HINTS:
            if pattern.search(name) or pattern.search(rel):
                if code in by_code:
                    ranked.setdefault(code, {
                        'code': code, 'name': by_code[code],
                        'score': 0.93, 'reason': 'filename',
                    })
                    break
    if not any(item['score'] >= 0.88 for item in ranked.values()) and labels:
        target = labels[0]
        best = None
        for name_key, code in by_name.items():
            score = SequenceMatcher(None, target, name_key).ratio()
            if best is None or score > best[0]:
                best = (score, code, name_key)
        if best and best[0] >= 0.86:
            ranked[best[1]] = {
                'code': best[1], 'name': by_code.get(best[1], best[2]),
                'score': round(best[0], 3), 'reason': 'fuzzy-name',
            }
    if not ranked:
        content = _suggest_from_content(draft, by_code)
        if content:
            ranked[content['code']] = content
    return sorted(ranked.values(), key=lambda x: (-x['score'], x['code']))[:3]


_CONTENT_HINTS = [
    (re.compile(r'(?i)вероятн|случайным образом'), 'STA.03.03'),
    (re.compile(r'(?i)процент'), 'ARI.04.04'),
    (re.compile(r'(?i)параллелограмм|трапец|ромб|четырёхуголь'), 'GEO.03'),
    (re.compile(r'(?i)окружност|касательн'), 'GEO.04'),
    (re.compile(r'(?i)треугольник|биссектрис|медиан'), 'GEO.02'),
    (re.compile(r'(?i)неравенств'), 'ALG.04'),
    (re.compile(r'(?i)уравнен'), 'ALG.03'),
    (re.compile(r'(?i)график|функци'), 'ALG.05'),
    (re.compile(r'(?i)\\sqrt|квадратн\w* корн'), 'ARI.05.01'),
    (re.compile(r'(?i)многочлен|разлож'), 'ALG.02'),
    (re.compile(r'(?i)смежн\w* угол|вертикальн\w* угол'), 'GEO.01.03'),
]


def _suggest_from_content(draft, by_code):
    votes = {}
    for el in draft.get('elements') or []:
        if el.get('kind') != 'task' or el.get('skip'):
            continue
        blob = ' '.join([
            el.get('text') or '',
            ' '.join(el.get('subitems') or []),
        ])
        for pattern, code in _CONTENT_HINTS:
            if code in by_code and pattern.search(blob):
                votes[code] = votes.get(code, 0) + 1
                break
    if not votes:
        return None
    code = max(votes, key=lambda c: (votes[c], len(c)))
    return {
        'code': code, 'name': by_code[code],
        'score': 0.88, 'reason': 'task-content',
    }


def Path_stem(rel_path):
    text = rel_path.replace('\\', '/').rsplit('/', 1)[-1]
    text = re.sub(r'\.tex$', '', text, flags=re.I)
    text = re.sub(r'^(math|alg|geom|matvert|oge|ege)\d*[-_]?', '', text, flags=re.I)
    text = text.replace('_', ' ').replace('-', ' ')
    return text


def _unique_codes(codes):
    seen = set()
    out = []
    for code in codes:
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def exam_codes_from_elements(elements, grade=None) -> list[str]:
    """\\oge / \\fipi / «ОГЭ» / «ЕГЭ» / «ФИПИ» в начале условия или рубрики."""
    codes = []
    for el in elements or []:
        kind = el.get('kind')
        if kind == 'task':
            head = (el.get('text') or '')[:120]
        elif kind == 'rubric':
            head = (el.get('rubric') or '')[:120]
        elif kind == 'text':
            head = (el.get('text') or '')[:80]
        else:
            continue
        if TASK_OGE_RE.search(head):
            codes.append('OGE_2026')
        if TASK_EGE_RE.search(head):
            if re.search(r'(?i)база|base', head):
                codes.append('EGE_BASE_2026')
            else:
                codes.append('EGE_PROFILE_2027')
        if TASK_FIPI_RE.search(head):
            if grade is not None and grade <= 9:
                codes.append('OGE_2026')
            else:
                codes.append('EGE_PROFILE_2027')
    return _unique_codes(codes)


def _exam_blobs(draft: dict) -> list[str]:
    """Сначала имя файла и заголовок, потом путь — чтобы oge9-course не перебил oge-01."""
    rel = draft.get('rel_path') or ''
    name = rel.replace('\\', '/').rsplit('/', 1)[-1]
    header = draft.get('header') or {}
    return [
        name,
        draft.get('title') or '',
        header.get('title') or '',
        header.get('left') or '',
        header.get('right') or '',
        header.get('subtitle') or '',
        rel,
    ]


def suggest_exams(draft: dict) -> list[str]:
    blobs = _exam_blobs(draft)
    blob = ' '.join(blobs)
    codes = []
    for text in blobs:
        m = OGE_RE.search(text)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 25:
                codes.append(f'OGE_2026_{num:02d}')
                break
    m = EGE_BASE_RE.search(blob)
    if m:
        num = int(m.group(1))
        if 1 <= num <= 21:
            codes.append(f'EGE_BASE_2026_{num:02d}')
    elif 'ege' in blob.lower() or 'егэ' in blob.lower():
        for text in blobs:
            m = EGE_RE.search(text) or EGE_STUCK_RE.search(text)
            if m:
                num = int(m.group(1))
                if 1 <= num <= 20:
                    codes.append(f'EGE_PROFILE_2027_{num:02d}')
                    break
        if not any(c.startswith('EGE_PROFILE') for c in codes):
            m = ZADANIE_RE.search(blob)
            if m:
                num = int(m.group(1))
                if 1 <= num <= 20:
                    codes.append(f'EGE_PROFILE_2027_{num:02d}')
    if MCKO_RE.search(blob):
        codes.append('MCKO_2026_01')
    if not any(c.startswith('OGE_') for c in codes):
        if re.search(r'(?i)(?<!math)(?<!ege)(?<!мцко)\b(?:огэ|oge)\b', blob):
            codes.append('OGE_2026')
    if not any(c.startswith('EGE_') for c in codes):
        if re.search(r'(?i)\b(?:егэ|ege)\b', blob):
            if re.search(r'(?i)\b(?:база|base)\b', blob):
                codes.append('EGE_BASE_2026')
            else:
                codes.append('EGE_PROFILE_2027')
    codes.extend(exam_codes_from_elements(
        draft.get('elements'), draft.get('grade')))
    codes = _unique_codes(codes)
    extra = []
    have = set(codes)
    for code in codes:
        line = None
        if code.startswith('OGE_2026_') and code != 'OGE_2026':
            line = 'OGE_2026'
        elif code.startswith('EGE_BASE_2026_') and code != 'EGE_BASE_2026':
            line = 'EGE_BASE_2026'
        elif (code.startswith('EGE_PROFILE_2027_')
              and code != 'EGE_PROFILE_2027'):
            line = 'EGE_PROFILE_2027'
        if line and line not in have:
            extra.append(line)
            have.add(line)
    return _unique_codes(codes + extra)


def _worksheet_topic_codes(draft):
    codes = []
    seen = set()
    for code in draft.get('topic_codes') or []:
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    primary = draft.get('topic_code') or ''
    if primary and primary not in seen:
        codes.insert(0, primary)
    return codes


def _element_topic_codes(el):
    codes = []
    seen = set()
    for code in el.get('topic_codes') or []:
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    primary = el.get('topic_code') or ''
    if primary and primary not in seen:
        codes.insert(0, primary)
    return codes


def _apply_topic_to_tasks(draft):
    """Копирует темы листка в задачи без собственной разметки."""
    _sync_copied_task_topics(draft, None)


def _sync_copied_task_topics(draft, old_codes):
    """Обновляет задачи, которые ещё несут прежний набор тем листка."""
    new_codes = _worksheet_topic_codes(draft)
    primary = draft.get('topic_code') or (new_codes[0] if new_codes else '')
    old_set = set(old_codes) if old_codes is not None else None
    for el in draft.get('elements') or []:
        if el.get('kind') != 'task':
            continue
        current = set(_element_topic_codes(el))
        copied = (not current
                  or (old_set is not None and current <= old_set))
        if not copied:
            continue
        el['topic_codes'] = list(new_codes)
        el['topic_code'] = primary


def _clear_copied_task_topics(draft, old_code):
    if not old_code:
        return
    old_set = {old_code}
    for el in draft.get('elements') or []:
        if el.get('kind') != 'task':
            continue
        current = set(_element_topic_codes(el))
        if not current or current <= old_set:
            el['topic_code'] = ''
            el['topic_codes'] = []


def _strip_topic_warning(draft):
    warns = [w for w in (draft.get('warnings') or [])
             if not str(w).startswith('Тема неуверенная')]
    draft['warnings'] = warns


def classify_draft(draft: dict, *, overwrite=False, recheck=False) -> dict:
    candidates = suggest_topic(draft)
    exams = suggest_exams(draft)
    draft['topic_candidates'] = candidates
    best = candidates[0] if candidates else None
    confident = topic_is_confident(best)
    old = draft.get('topic_code') or ''
    if overwrite or recheck or not old:
        if confident:
            if old and old != best['code']:
                _clear_copied_task_topics(draft, old)
            draft['topic_code'] = best['code']
            draft['topic_codes'] = [best['code']]
            draft['needs_topic_review'] = False
        else:
            if recheck or overwrite or not old:
                _clear_copied_task_topics(draft, old)
                draft['topic_code'] = ''
                draft['topic_codes'] = []
            draft['needs_topic_review'] = True
        _strip_topic_warning(draft)
    if overwrite or not draft.get('exam_item_codes'):
        draft['exam_item_codes'] = exams
    _apply_topic_to_tasks(draft)
    return draft


def classify_all(*, overwrite=False, recheck=False,
                 skip_statuses=('skipped', 'imported')):
    rows = []
    skip = set(skip_statuses or ())
    for path in iter_draft_paths():
        draft = load_json(path)
        if not draft:
            continue
        if draft.get('status') in skip:
            continue
        classify_draft(draft, overwrite=overwrite, recheck=recheck)
        save_draft(draft)
        rows.append(draft)
    classify_report_path().write_text(render_classify_report(rows),
                                      encoding='utf-8')
    return rows


def render_classify_report(drafts):
    lines = [
        '# Темы и экзаменационные метки',
        '',
        f'Черновиков: **{len(drafts)}**.',
        '',
        '| Листок | Тема | Экзамен | Замечание |',
        '| --- | --- | --- | --- |',
    ]
    doubtful = []
    for draft in drafts:
        topic = draft.get('topic_code') or '—'
        exams = ', '.join(draft.get('exam_item_codes') or []) or '—'
        note = ''
        if draft.get('needs_topic_review') or (
                not draft.get('topic_code')):
            note = 'проверить тему'
            doubtful.append(draft)
        lines.append(
            f'| `{draft.get("id")}` | {topic} | {exams} | {note} |')
    lines.extend(['', f'Без уверенной темы: {len(doubtful)}.', ''])
    return '\n'.join(lines)
