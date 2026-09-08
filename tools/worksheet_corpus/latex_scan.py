"""Низкоуровневый разбор групп и окружений LaTeX без Django."""

from __future__ import annotations

import re
from pathlib import Path

GRAPHIC_RE = re.compile(
    r'\\(?:includegraphics|taskpic)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}')
TASKPIC_INDEX_RE = re.compile(r'^\d+$')


def skip_space(text, pos):
    n = len(text)
    while pos < n:
        c = text[pos]
        if c in ' \t\r\n':
            pos += 1
        elif c == '%':
            while pos < n and text[pos] != '\n':
                pos += 1
        else:
            break
    return pos


def read_group(text, pos, open_ch='{', close_ch='}'):
    """Читает сбалансированную группу. Возвращает (тело, pos_после) или (None, pos)."""
    pos = skip_space(text, pos)
    if pos >= len(text) or text[pos] != open_ch:
        return None, pos
    brace = 0
    bracket = 0
    i = pos + 1
    start = i
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            brace += 1
        elif c == '}':
            if brace == 0 and close_ch == '}':
                return text[start:i], i + 1
            brace -= 1
        elif brace == 0 and close_ch == ']':
            if c == '[':
                bracket += 1
            elif c == ']':
                if bracket == 0:
                    return text[start:i], i + 1
                bracket -= 1
        i += 1
    return None, pos


def read_command_args(text, pos, required, optional=0):
    args = []
    for _ in range(required):
        value, pos = read_group(text, pos, '{', '}')
        if value is None:
            return None, pos
        args.append(value)
    opts = []
    for _ in range(optional):
        value, new_pos = read_group(text, pos, '[', ']')
        if value is None:
            break
        opts.append(value)
        pos = new_pos
    return (args, opts), pos


def strip_comments_line(text):
    """Убирает незаэкранированный % до конца строки."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\' and i + 1 < n:
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == '%':
            while i < n and text[i] != '\n':
                i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def document_body(source):
    m = re.search(r'\\begin\{document\}', source)
    if not m:
        return source
    body = source[m.end():]
    m_end = re.search(r'\\end\{document\}', body)
    if m_end:
        body = body[:m_end.start()]
    return body


def extract_graphics(text, names):
    def repl(match):
        name = match.group(1).strip()
        if not name:
            return ''
        # \\taskpic{1} — уже ссылка на картинку задачи, не имя файла.
        if TASKPIC_INDEX_RE.fullmatch(name):
            return match.group(0)
        if name not in names:
            names.append(name)
        return '\\taskpic{%d}' % (names.index(name) + 1)
    return GRAPHIC_RE.sub(repl, text)


def clean_arg(text):
    return re.sub(r'%\s*\n', '\n', text).strip()


def split_items(text):
    """Режет по \\item; хвостовую служебную пунктуацию снимаем."""
    chunks = _ITEM_RE.split(text)
    out = []
    for chunk in chunks:
        piece = strip_subitem_punct(chunk)
        if piece:
            out.append(piece)
    return out


_ITEM_RE = re.compile(r'\\item\b')


TRAILING_LAYOUT_TAIL_RE = re.compile(
    r'(?:\\(?:quad|qquad|parn|par|hfill)|\\\\)+\s*$')


def strip_trailing_layout(text):
    """Срезает хвостовые \\quad/\\par/\\\\, оставшиеся от колоночной вёрстки."""
    text = (text or '').rstrip()
    while True:
        nxt = TRAILING_LAYOUT_TAIL_RE.sub('', text).rstrip()
        if nxt == text:
            return text
        text = nxt


def strip_subitem_punct(text):
    text = strip_trailing_layout((text or '').strip())
    if not text:
        return text
    if text.endswith('?'):
        return text
    if text[0].isupper() and text.endswith('.'):
        return text
    if text.endswith((';', '.', ',')):
        text = text[:-1].rstrip()
        text = strip_trailing_layout(text)
    text = re.sub(r'\.\s*(\$+)\s*$', r'\1', text)
    return text


def _token_at(text, pos, token):
    """Точное совпадение токена: \\begin{enumerate} не захватывает enumerate*."""
    if not text.startswith(token, pos):
        return False
    nxt = pos + len(token)
    if nxt < len(text) and (text[nxt].isalnum() or text[nxt] in '*@'):
        return False
    return True


def _find_token(text, token, start=0):
    pos = start
    while True:
        i = text.find(token, pos)
        if i < 0:
            return -1
        if _token_at(text, i, token):
            return i
        pos = i + 1


def find_env_spans(text, env):
    """Интервалы \\begin{env}...\\end{env} с учётом вложенности того же env."""
    begin = r'\begin{%s}' % env
    end = r'\end{%s}' % env
    spans = []
    pos = 0
    while True:
        start = _find_token(text, begin, pos)
        if start < 0:
            break
        depth = 1
        i = start + len(begin)
        while i < len(text) and depth:
            nxt_b = _find_token(text, begin, i)
            nxt_e = _find_token(text, end, i)
            if nxt_e < 0:
                break
            if nxt_b >= 0 and nxt_b < nxt_e:
                depth += 1
                i = nxt_b + len(begin)
            else:
                depth -= 1
                if depth == 0:
                    inner_start = start + len(begin)
                    spans.append((start, nxt_e + len(end),
                                  text[inner_start:nxt_e]))
                    i = nxt_e + len(end)
                    break
                i = nxt_e + len(end)
        pos = i if i > start else start + 1
    return spans


def split_top_items(body):
    """Делит содержимое enumerate на пункты верхнего уровня."""
    items = []
    pos = 0
    depth = 0
    current = None
    n = len(body)
    begin_enum = '\\begin{enumerate}'
    end_enum = '\\end{enumerate}'
    begin_itemz = '\\begin{itemize}'
    end_itemz = '\\end{itemize}'
    while pos < n:
        if body.startswith(begin_enum, pos) or body.startswith(begin_itemz, pos):
            depth += 1
            if current is not None:
                current.append(begin_enum if body.startswith(begin_enum, pos)
                               else begin_itemz)
            pos += len(begin_enum)
            continue
        if body.startswith(end_enum, pos) or body.startswith(end_itemz, pos):
            token = end_enum if body.startswith(end_enum, pos) else end_itemz
            if current is not None:
                current.append(token)
            depth = max(0, depth - 1)
            pos += len(token)
            continue
        if depth == 0 and body.startswith('\\item', pos):
            if current is not None:
                items.append(''.join(current).strip())
            current = []
            pos += len('\\item')
            # необязательная метка [1.]
            if pos < n and body[pos] == '[':
                close = body.find(']', pos)
                if close >= 0:
                    pos = close + 1
            continue
        if current is not None:
            current.append(body[pos])
        pos += 1
    if current is not None:
        items.append(''.join(current).strip())
    return [item for item in items if item]


TITLE_WRAP_RE = re.compile(
    r'\\(?:textbf|textit|emph|textsf|textrm|texttt|textmd|underline)'
    r'\{([^{}]*)\}')
TITLE_SIZE_RE = re.compile(
    r'\\(?:tiny|scriptsize|footnotesize|small|normalsize|large|Large|'
    r'LARGE|huge|Huge|bf|it|sl|sf|rm|tt)\b')
TITLE_DROP_RE = re.compile(
    r'\\(?:parn|par|noindent|bigskip|medskip|smallskip|hfill|vfill|'
    r'centering|centerline|linebreak|newline|hspace|vspace|mbox|hbox)'
    r'(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?')
TITLE_CMD_RE = re.compile(
    r'\\[a-zA-Z]+\*?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?')
HEADERISH_TITLE_RE = re.compile(
    r'(?i)математическая\s+вертикаль|'
    r'гбоу\s*школа|'
    r'учебный\s+год|'
    r'^\s*\d+\s*класс\.?\s*$|'
    r'^\s*математика\s*$')


def clean_title_text(text):
    """Убирает \\par, \\Large и прочий шум колонтитулов из названия."""
    text = (text or '').replace(r'\%', '%')
    text = re.sub(r'(?<!\\)%[^\n]*', ' ', text)
    text = text.replace('\\\\', ' ')
    text = TITLE_WRAP_RE.sub(r'\1', text)
    text = TITLE_SIZE_RE.sub(' ', text)
    text = TITLE_DROP_RE.sub(' ', text)
    text = TITLE_CMD_RE.sub(' ', text)
    text = re.sub(r'[{}\\]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip(' \t.;,')


def is_headerish_title(text):
    return bool(HEADERISH_TITLE_RE.search(text or ''))


TITLE_PROPOSED_WARNING = 'Заголовок предложен по содержанию'

_LATIN_RE = re.compile(r'[A-Za-z]')
_CYR_RE = re.compile(r'[А-Яа-яЁё]')


def title_from_filename(rel_path):
    stem = Path(rel_path).stem if rel_path else ''
    stem = re.sub(
        r'^(math|alg|geom|matvert|oge|ege|mcko)\d*[-_]?',
        '', stem, flags=re.I)
    stem = stem.replace('_', ' ').replace('-', ' ').strip()
    if not stem:
        return ''
    return stem[:1].upper() + stem[1:]


def title_looks_from_filename(title, rel_path):
    """True, если название — транслит/stem файла, а не учебный заголовок."""
    title = (title or '').strip()
    from_fn = title_from_filename(rel_path)
    if not title:
        return True
    if from_fn and title.lower() == from_fn.lower():
        return True
    lat = len(_LATIN_RE.findall(title))
    cyr = len(_CYR_RE.findall(title))
    return lat >= 3 and lat > cyr * 2


def apply_proposed_title(draft, title):
    """Ставит учебный заголовок и пометку для ручной сверки."""
    title = clean_title_text(title)
    draft['title'] = title
    header = dict(draft.get('header') or {})
    header['title'] = title
    draft['header'] = header
    draft['title_origin'] = 'proposed'
    warnings = list(draft.get('warnings') or [])
    if TITLE_PROPOSED_WARNING not in warnings:
        warnings.append(TITLE_PROPOSED_WARNING)
    draft['warnings'] = warnings
    return draft


def _usable_title(text):
    cleaned = clean_title_text(text)
    if not cleaned or is_headerish_title(cleaned):
        return ''
    return cleaned


def extract_title_guess(source, body=None):
    """Заголовок из \\bighead, \\head или первого Large-блока.

    \\title{Математическая вертикаль…} и колонтитулы отбрасываются.
    """
    candidates = []
    m = re.search(
        r'\\bighead\s*\{([^{}]*)\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}'
        r'(?:\s*\[([^\]]*)\])?',
        source)
    if m:
        candidates.append({
            'title': m.group(1),
            'left': m.group(2),
            'right': m.group(3),
            'subtitle': m.group(4) or '',
        })
    m = re.search(r'\\head\s*\{([^{}]*)\}\s*\{([^{}]*)\}', source)
    if m:
        candidates.append({
            'title': m.group(1),
            'left': m.group(2),
            'right': '',
            'subtitle': '',
        })
    m = re.search(r'\\mathhead\s*\{([^{}]*)\}', source)
    if m:
        candidates.append({
            'title': m.group(1),
            'left': '', 'right': '', 'subtitle': '',
        })
    blob = body if body is not None else document_body(source)
    m = re.search(
        r'\\begin\{center\}[\s\S]{0,400}?\\Large\s*\{?([^}{]+)\}?',
        blob)
    if m:
        candidates.append({
            'title': m.group(1),
            'left': '', 'right': '', 'subtitle': '',
        })
    m = re.search(r'\\title\s*\{([^{}]+)\}', source)
    if m:
        candidates.append({
            'title': m.group(1),
            'left': '', 'right': '', 'subtitle': '',
        })
    for raw in candidates:
        title = _usable_title(raw['title'])
        if title:
            return {
                'title': title,
                'left': clean_title_text(raw.get('left') or ''),
                'right': clean_title_text(raw.get('right') or ''),
                'subtitle': clean_title_text(raw.get('subtitle') or ''),
            }
    return {'title': '', 'left': '', 'right': '', 'subtitle': ''}


def _unescape_simple(text):
    return clean_title_text(text)


ALPHA_SUB_RE = re.compile(
    r'(?m)(?:^|(?<=\n)|(?<=\\\\)|(?<=\\par)|(?<=\s))'
    r'(?P<label>[а-яёa-z])\)\s*[~]?',
    re.I)


CHOICE_ENVS = (
    'oneparcheckboxes', 'oneparchoices', 'checkboxes', 'choices',
)
TRAILING_EXAM_GLUE_RE = re.compile(
    r'(?:\\vspace\*?\{[^}]*\}|\\(?:medskip|bigskip|smallskip|parn|par|'
    r'noindent|hfill)|~|\\quad|\\qquad|\s)+$')
GRID_PREFIX_RE = re.compile(
    r'(?:\\vspace\*?\{[^}]*\}|\\(?:medskip|bigskip|smallskip|parn|par|'
    r'noindent|hfill)|~|\\quad|\\qquad|\s)+$')
TIKZ_OPT_RE = re.compile(r'^(\[[^\]]*\])\s*')
TIKZ_GRID_DRAW_RE = re.compile(
    r'^\\draw\s*(?:\[[^\]]*\])?\s*\([^)]+\)\s*grid'
    r'(?:\[[^\]]*\])?\s*\([^)]+\)\s*;?\s*$')


def strip_trailing_exam_glue(text):
    return TRAILING_EXAM_GLUE_RE.sub('', text or '').strip()


def extract_choice_envs(text):
    """Вынимает \\choice из exam-окружений, сами окружения из текста убирает."""
    remaining = text or ''
    found = []
    for env in CHOICE_ENVS:
        for start, end, inner in find_env_spans(remaining, env):
            found.append((start, end, inner))
    found.sort(key=lambda item: item[0])
    choices = []
    for _start, _end, inner in found:
        for piece in re.split(r'\\choice\b', inner)[1:]:
            item = clean_arg(piece)
            if item:
                choices.append(item)
    for start, end, _inner in reversed(found):
        remaining = remaining[:start] + remaining[end:]
    return strip_trailing_exam_glue(remaining), choices


def _is_answer_grid_tikz(inner):
    body = TIKZ_OPT_RE.sub('', inner or '')
    body = re.sub(r'(?<!\\)%[^\n]*', '', body)
    body = re.sub(r'\s+', ' ', body).strip()
    if not body or 'grid' not in body:
        return False
    parts = [p.strip() for p in body.split(';') if p.strip()]
    return bool(parts) and all(TIKZ_GRID_DRAW_RE.match(part) for part in parts)


LAYOUT_SPACE_RE = re.compile(
    r'\\vspace\*?\{[^{}]*\}|\\hspace\*?\{[^{}]*\}|'
    r'\\(?:medskip|bigskip|smallskip)\b')
NOINDENT_RE = re.compile(r'\\noindent\b')
SETCOUNTER_RE = re.compile(
    r'\\setcounter\s*\{[^{}]+\}\s*\{(?:[^{}]|\\[a-zA-Z]+\{[^{}]+\})*\}')
COMMENTED_MULTICOLS_RE = re.compile(
    r'(?:^|\s)*%+\s*\\begin\{multicols\}[^\n%]*'
    r'(?:\s*%+\s*\\end\{multicols\}[^\n]*)?',
    re.M)
HANGING_MULTICOLS_END_RE = re.compile(r'\\end\{multicols\}')


def _unwrap_multicols(text):
    remaining = text or ''
    while True:
        spans = find_env_spans(remaining, 'multicols')
        if not spans:
            break
        start, end, inner = spans[0]
        inner = re.sub(r'^\s*\{\d+\}\s*', '', inner or '')
        inner = re.sub(r'(?<!\\)%[^\n]*', '', inner).strip()
        remaining = remaining[:start] + inner + remaining[end:]
    remaining = COMMENTED_MULTICOLS_RE.sub('', remaining)
    remaining = HANGING_MULTICOLS_END_RE.sub('', remaining)
    remaining = re.sub(r'\\begin\{multicols\}\{\d+\}', '', remaining)
    return remaining


def strip_layout_space(text):
    """Убирает служебную вёрстку исходных tex: vspace, multicols, setcounter."""
    text = strip_comments_line(text or '')
    text = _unwrap_multicols(text)
    text = SETCOUNTER_RE.sub('', text)
    text = LAYOUT_SPACE_RE.sub('', text)
    text = NOINDENT_RE.sub('', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return strip_trailing_layout(text.strip())


def strip_answer_grids(text):
    """Убирает tikz-сетку для записи ответа и \\vspace/\\noindent перед ней."""
    remaining = text or ''
    spans = find_env_spans(remaining, 'tikzpicture')
    for start, end, inner in reversed(spans):
        if not _is_answer_grid_tikz(inner):
            continue
        prefix = remaining[:start]
        match = GRID_PREFIX_RE.search(prefix)
        if match:
            start = match.start()
        remaining = remaining[:start] + remaining[end:]
    return remaining.strip()


def split_alpha_subitems(text):
    """Режет «а)~ … б)~ …» на подпункты. Если меток меньше двух — как есть."""
    matches = list(ALPHA_SUB_RE.finditer(text))
    if len(matches) < 2:
        return text.strip(), []
    stem = text[:matches[0].start()].strip()
    parts = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = strip_subitem_punct(text[match.end():end])
        if chunk:
            parts.append(chunk)
    return stem, parts
