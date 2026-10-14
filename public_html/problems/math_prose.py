"""Проза внутри формул: вынос русского текста из ``$…$`` наружу.

Распознанный (Mathpix/OCR) текст часто приходит целой формулой:
``$\\text { Даны точки } M(1 ; 1) \\text { и } N(4 ;-1) .$``. На сайте такой
текст идёт шрифтом формулы, не переносится, а пробел в начале ``\\text { …}``
даёт лишний отступ первой строки. ``unwrap_math_prose`` превращает это в
обычную строку с формулами: ``Даны точки $M(1 ; 1)$ и $N(4 ;-1)$.``

Сначала жил в импорте Шабунина; теперь общий — им же чинятся уже
загруженные задачи (``manage.py unwrap_math_prose``) и импорт корпуса.
"""
import re

_DOLLAR_SPAN_RE = re.compile(r"(?<!\$)\$(?!\$)[^$]*\$")


# Проза внутри строчной формулы («$\ln ^{2} x>… \text { при } x>2$»): на
# сайте русский текст в формуле идёт чужим шрифтом и не переносится.
# Выносим \text{…} с кириллицей наружу, только вне скобок и окружений:
# «если» в кусочной функции, русские индексы и \operatorname остаются.
_TEXT_CMD_RE = re.compile(r"\\(?:text|mbox|textrm)\s*\{")
_PROSE_DEPTH_RE = re.compile(
    r"\\(?:left|begin)(?![a-zA-Z])|(?<!\\)\{|\\(?:right|end)(?![a-zA-Z])|(?<!\\)\}")


def _brace_end(text: str, opening: int) -> int:
    depth = 0
    for pos in range(opening, len(text)):
        char = text[pos]
        if char == "\\":
            continue
        if char == "{" and text[pos - 1] != "\\":
            depth += 1
        elif char == "}" and text[pos - 1] != "\\":
            depth -= 1
            if depth == 0:
                return pos
    return -1


def _split_math_prose(body: str) -> list[tuple[bool, str]] | None:
    """[(формула?, кусок)] или None, если прозы на верхнем уровне нет."""
    pieces = []
    depth = 0
    start = pos = 0
    found = False
    while pos < len(body):
        command = _TEXT_CMD_RE.match(body, pos)
        if command and depth == 0:
            end = _brace_end(body, command.end() - 1)
            content = body[command.end():end] if end > 0 else ""
            # Русские слова и знаки предложения («\text {. }») — проза.
            # Но не единица со степенью или индексом («5 \text{ см}^{2}»,
            # «\text{м}_{1}», «\text{мин}'»): вынос оторвал бы ² от единицы.
            if end > 0 and (re.search(r"[А-Яа-яЁё]", content)
                            or re.fullmatch(r"[\s.,;:]+", content)) \
                    and not re.match(r"\s*['^_]", body[end + 1:]):
                pieces.append((True, body[start:pos]))
                pieces.append((False, content))
                found = True
                start = pos = end + 1
                continue
        token = _PROSE_DEPTH_RE.match(body, pos)
        if token:
            opening = token.group(0) in ("{",) or token.group(0).startswith(("\\left", "\\begin"))
            depth += 1 if opening else -1
            pos = token.end()
            continue
        pos += 2 if body.startswith("\\", pos) else 1
    pieces.append((True, body[start:]))
    if not found or depth != 0 or not any(
            re.search(r"[А-Яа-яЁё]", piece) for is_math, piece in pieces if not is_math):
        return None
    return pieces


_FLAT_SET_PAIR_RE = re.compile(r"\\left\\\{((?:(?!\\left|\\right).)*?)\\right\\\}", re.S)


_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)


def unwrap_math_prose(value: str, display: bool = True) -> str:
    """Строчная формула с прозой — формулы и текст вперемешку; выключная
    («$$\ln … \text { при } x>2 .$$») — строка текста со строчными.

    ``display=False`` — выключные формулы не трогать (починка уже
    загруженных задач: там вынос из ``\[…\]`` меняет вид условия)."""
    def fix_display(match: re.Match) -> str:
        body = match.group(1) or match.group(2)
        fixed = fix_body(body, display=True)
        return match.group(0) if fixed is None else fixed

    def fix(match: re.Match) -> str:
        fixed = fix_body(match.group(0)[1:-1])
        return match.group(0) if fixed is None else fixed

    def fix_body(body: str, display: bool = False) -> str | None:
        if not _TEXT_CMD_RE.search(body):
            return None
        # Скобки множества вокруг фразы («\left\{\text{Число} …\right\}»)
        # — обычные: после выноса фразы половины окажутся в разных формулах.
        plain = _FLAT_SET_PAIR_RE.sub(r"\\{\1\\}", body)
        pieces = _split_math_prose(plain)
        if pieces is None:
            return None
        display = display or body.lstrip().startswith("\\displaystyle")
        out = ""
        for is_math, piece in pieces:
            piece = " ".join(piece.split())
            if is_math:
                piece = re.sub(r"^\\displaystyle\s*", "", piece)
                # «\right .» — тот же разделитель «\right.», не точка предложения.
                piece = re.sub(r"\\right\s+\.", r"\\right.", piece)
                # Отступы на краю формулы перед прозой («x>0 \; \text{при}») не нужны.
                piece = re.sub(r"(?:\s*\\(?:[,;:!]|q?quad(?![a-zA-Z])))+\s*$", "", piece)
                piece = re.sub(r"^(?:\\(?:[,;:!]|q?quad(?![a-zA-Z]))\s*)+", "", piece)
                # Знак предложения в конце формулы («…\frac{2}{y-3},», «2,9 .»)
                # — за формулу; точку «\right.» и команды «\;», «\,» не трогаем.
                tail = re.search(r"\s*([,.;:])$", piece)
                if tail and (piece[:tail.start(1)].endswith("\\")
                             or piece[:tail.start(1)].endswith("\\right")):
                    tail = None
                if tail:
                    piece = piece[:tail.start()].rstrip()
                if not piece:
                    continue
                if display and "\\frac" in piece:
                    piece = "\\displaystyle " + piece
                glue = "" if not out or out.endswith((" ", "(")) or piece.startswith("\\}") else " "
                out += glue + "$" + piece + "$" + (tail.group(1) if tail else "")
            elif piece:
                glue = "" if not out or piece[0] in ".,;:)" or out.endswith("\\{$") else " "
                out += glue + piece
        return out.strip()

    value = value or ""
    if display:
        value = _DISPLAY_MATH_RE.sub(fix_display, value)
    return _DOLLAR_SPAN_RE.sub(fix, value)
