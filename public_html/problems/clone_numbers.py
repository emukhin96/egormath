"""Числа в LaTeX-условии для быстрого клона задачи.

``find_numbers`` находит числовые литералы, которые учитель меняет в клоне:
целые и десятичные (``2.5``, ``2{,}5``, ``2,5``). Минус — отдельный знак,
в число не входит. Не считаются числами для замены:

* имена команд и аргументы служебных команд (``\\taskpic{1}``,
  ``\\includegraphics``, ``\\vspace``/``\\hspace``, ``\\label``/``\\ref``…);
* размеры с единицами (``3cm``, ``0.5\\textwidth``, ``\\\\[2mm]``);
* показатели и индексы (``x^2``, ``x^{12}``, ``a_1``, ``b_{n+1}``) и
  показатель корня ``\\sqrt[3]{…}``;
* описание колонок ``\\begin{tabular}{|c|c|}``/``array``, окружения
  рисунков (``tikzpicture``, ``picture``) и комментарии ``%…``.

Та же логика продублирована в ``static/js/quick_clone.js`` (числа в
новом ответе для синхронизации маски на клиенте); сервер при сохранении
пересчитывает маску здесь.
"""
import re
from decimal import Decimal, InvalidOperation

NUMBER_RE = re.compile(r'[0-9]+(?:(?:\.|\{,\}|,)[0-9]+)?')
LETTERS = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
DIGITS = frozenset('0123456789')
# Размер с единицей: 3cm, 2 mm, 0.5\textwidth
UNIT_RE = re.compile(
    r'\s*(?:(?:pt|mm|cm|in|ex|em|bp|pc|dd|cc|sp|mu)(?![A-Za-z])|'
    r'\\(?:textwidth|linewidth|columnwidth|textheight|paperwidth|hsize|'
    r'vsize|baselineskip|parindent|fill)(?![A-Za-z]))')
# Команда → сколько обязательных аргументов пропустить целиком
SKIP_ARGS = {
    'taskpic': 1, 'includegraphics': 1, 'vspace': 1, 'hspace': 1,
    'label': 1, 'ref': 1, 'eqref': 1, 'pageref': 1, 'cite': 1,
    'url': 1, 'href': 1, 'input': 1, 'include': 1,
    'setlength': 2, 'addtolength': 2, 'setcounter': 2, 'addtocounter': 2,
    'color': 1, 'textcolor': 1, 'colorbox': 1, 'cline': 1,
    'multicolumn': 2, 'multirow': 2, 'rule': 2,
    'parbox': 1, 'raisebox': 1, 'enlargethispage': 1,
}
# Команды с необязательным аргументом […]: его содержимое не меняем
OPTIONAL_ARGS = {
    'sqrt', 'makebox', 'framebox', 'parbox', 'raisebox', 'includegraphics',
    'item', 'rule', 'multirow', 'newline', 'linebreak', 'taskpic',
}
# Окружение → сколько аргументов после \begin{…} пропустить
ENV_ARGS = {
    'tabular': 1, 'tabular*': 2, 'tabularx': 2, 'array': 1, 'longtable': 1,
    'minipage': 1, 'multicols': 1, 'wrapfigure': 2,
}
# Окружения целиком без замен: координаты рисунка
SKIP_ENVS = {'tikzpicture', 'picture', 'pspicture'}
SLOT_OPTION_KINDS = {'choice', 'order', 'compare', 'sign', 'yesno',
                     'truefalse', 'parity'}


def _skip_group(text, i):
    """``text[i] == '{'`` → индекс после парной ``}``."""
    depth = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _skip_optional(text, i):
    """``text[i] == '['`` → индекс после парной ``]`` (с учётом ``{}``)."""
    n = len(text)
    i += 1
    while i < n:
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '{':
            i = _skip_group(text, i)
            continue
        if ch == ']':
            return i + 1
        i += 1
    return n


def _skip_spaces(text, i):
    while i < len(text) and text[i] in ' \t\r\n':
        i += 1
    return i


def _skip_args(text, i, count, optional=False):
    """Пропускает ``count`` обязательных аргументов (и […] перед ними)."""
    while True:
        if optional and i < len(text) and text[i] == '[':
            i = _skip_optional(text, i)
            continue
        if count <= 0:
            return i
        j = _skip_spaces(text, i)
        if j < len(text) and text[j] == '{':
            i = _skip_group(text, j)
        elif j < len(text) and text[j] not in '\\}':
            i = j + 1
        else:
            return i
        count -= 1


def _skip_script(text, i):
    """После ``^``/``_``: один токен — группа, команда или символ."""
    i = _skip_spaces(text, i)
    if i >= len(text):
        return i
    if text[i] == '{':
        return _skip_group(text, i)
    if text[i] == '\\':
        j = i + 1
        if j < len(text) and text[j] in LETTERS:
            while j < len(text) and text[j] in LETTERS:
                j += 1
            return j
        return j + 1
    return i + 1


def find_numbers(text):
    """Список ``(start, end, value)`` редактируемых чисел в LaTeX-тексте."""
    text = text or ''
    found = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == '%':
            end = text.find('\n', i)
            i = n if end < 0 else end + 1
            continue
        if ch == '\\':
            j = i + 1
            if j < n and text[j] in LETTERS:
                while j < n and text[j] in LETTERS:
                    j += 1
                name = text[i + 1:j]
                if j < n and text[j] == '*':
                    j += 1
                    name += '*'
                base = name.rstrip('*')
                if base == 'begin':
                    k = _skip_spaces(text, j)
                    if k < n and text[k] == '{':
                        close = _skip_group(text, k)
                        env = text[k + 1:close - 1].strip()
                        if env in SKIP_ENVS:
                            end = text.find('\\end{' + env + '}', close)
                            i = n if end < 0 else end
                            continue
                        j = _skip_args(text, close, ENV_ARGS.get(env, 0),
                                       optional=True)
                elif base == 'end':
                    j = _skip_args(text, j, 1)
                else:
                    j = _skip_args(text, j, SKIP_ARGS.get(base, 0),
                                   optional=base in OPTIONAL_ARGS)
                i = j
                continue
            # \\, \%, \{ и т.п.; после \\ — необязательный [2mm]
            j = min(i + 2, n)
            if text[i + 1:i + 2] == '\\':
                if j < n and text[j] == '*':
                    j += 1
                if j < n and text[j] == '[':
                    j = _skip_optional(text, j)
            i = j
            continue
        if ch in '^_':
            i = _skip_script(text, i + 1)
            continue
        if ch in DIGITS:
            m = NUMBER_RE.match(text, i)
            end = m.end()
            # «1,2,3» — перечень, а не десятичные дроби
            if ',' in m.group() and '{,}' not in m.group() and (
                    re.match(r',[0-9]', text[end:end + 2])
                    or (i >= 2 and text[i - 1] == ',' and text[i - 2] in DIGITS)):
                end = i + m.group().index(',')
            if UNIT_RE.match(text, end):
                i = end
                continue
            found.append((i, end, text[i:end]))
            i = end
            continue
        i += 1
    return found


def split_numbers(text):
    """Текст → сегменты ``{'text': …}`` и ``{'num': …, 'index': k}``."""
    text = text or ''
    segments = []
    pos = 0
    for index, (start, end, value) in enumerate(find_numbers(text)):
        if start > pos:
            segments.append({'text': text[pos:start]})
        segments.append({'num': value, 'index': index})
        pos = end
    if pos < len(text):
        segments.append({'text': text[pos:]})
    return segments


def replace_numbers(text, values):
    """Подставляет ``values`` вместо найденных чисел по порядку."""
    numbers = find_numbers(text)
    if len(values) != len(numbers):
        raise ValueError('Число значений не совпадает с числом чисел в тексте')
    parts = []
    pos = 0
    for (start, end, _), value in zip(numbers, values):
        parts.append(text[pos:start])
        parts.append(str(value))
        pos = end
    parts.append(text[pos:])
    return ''.join(parts)


def number_value(literal):
    """``2{,}5`` / ``2,5`` / ``2.5`` → Decimal для сравнения."""
    try:
        return Decimal(literal.replace('{,}', '.').replace(',', '.'))
    except InvalidOperation:
        return None


# --- маска, которая следует за ответом ---------------------------------------

def mask_numbers(mask):
    """Числа в эталонах слотов маски: ``(start, end, value)`` в тексте маски.

    Берётся тело слота до опций ``| …`` и допуска ``~ …``. Слоты выбора
    (choice, order, пресеты) с цифрами делают маску «сложной» — ``None``.
    """
    from assignments.checks.mask import _OPEN_RE, _find_close
    mask = mask or ''
    result = []
    pos = 0
    while True:
        m = _OPEN_RE.search(mask, pos)
        if not m:
            break
        close = _find_close(mask, m.end())
        if close < 0:
            return None
        body_start, body = m.end(), mask[m.end():close]
        if m.group(1) in SLOT_OPTION_KINDS:
            if re.search(r'[0-9]', body):
                return None
        else:
            cut = len(body)
            for sep in ('|', '~'):
                at = body.find(sep)
                if at >= 0:
                    cut = min(cut, at)
            for start, end, value in find_numbers(body[:cut]):
                result.append((body_start + start, body_start + end, value))
        pos = close + 2
    return result


def _same_values(left, right):
    return len(left) == len(right) and all(
        number_value(a) == number_value(b) for a, b in zip(left, right))


def mask_follows_answer(mask, answer):
    """Маска «простая»: числа её эталонов — ровно числа ответа по порядку."""
    slots = mask_numbers(mask)
    if not slots:
        return False
    return _same_values([v for _, _, v in slots],
                        [v for _, _, v in find_numbers(answer)])


def follow_mask(mask, old_answer, new_answer):
    """Новая маска для нового ответа или ``None``, если маска не простая
    или в новом ответе другое количество чисел."""
    if not mask_follows_answer(mask, old_answer):
        return None
    new_values = [v for _, _, v in find_numbers(new_answer)]
    slots = mask_numbers(mask)
    if len(new_values) != len(slots):
        return None
    parts = []
    pos = 0
    for (start, end, _), value in zip(slots, new_values):
        parts.append(mask[pos:start])
        # В маске десятичная запятая без фигурных скобок
        parts.append(value.replace('{,}', ','))
        pos = end
    parts.append(mask[pos:])
    return ''.join(parts)
