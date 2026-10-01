"""Генерация .tex-документа листка на пакете egor.

Текст задач хранится в базе как доверенный LaTeX (его пишут учителя),
экранируются только «обычные» поля: название листка, класс, автор.
"""

import hashlib
import re

from problems.latex_utils import escape_latex

# Опции \usepackage{egor} по вариантам сборки
VARIANT_OPTIONS = {
    'student': '',
    'answers': 'answers=table',
    'teacher': 'answers=inline,solutions',
}

PDF_OPTION_VALUES = {
    'size': {'10pt', '11pt', '12pt'},
    'paper': {'a4paper', 'a5paper'},
    'font': {'cm', 'school', 'palatino', 'stix'},
    'diagn': {'off', 'on'},
}
EGOR_PACKAGE_RE = re.compile(r'\\usepackage(?:\[([^\]]*)\])?\{egor\}')


def pdf_options_from_tex(tex):
    """Извлекает только поддерживаемые быстрые настройки из TeX."""
    document = re.search(r'\\documentclass(?:\[([^\]]*)\])?\{article\}', tex)
    class_options = ((document.group(1) if document else '') or '').split(',')
    package = EGOR_PACKAGE_RE.search(tex)
    egor_options = ((package.group(1) if package else '') or '').split(',')
    raw = {
        'size': next((x.strip() for x in class_options
                      if x.strip() in PDF_OPTION_VALUES['size']), '10pt'),
        'paper': next((x.strip() for x in class_options
                       if x.strip() in PDF_OPTION_VALUES['paper']), 'a4paper'),
        'font': next((x.strip().split('=', 1)[1] for x in egor_options
                      if x.strip().startswith('font=')), 'cm'),
        'diagn': 'on' if 'diagn' in {x.strip() for x in egor_options} else 'off',
    }
    return {key: value for key, value in raw.items()
            if value in PDF_OPTION_VALUES[key]}


def apply_pdf_options(tex, options):
    """Применяет сохранённое оформление к свежему TeX листка."""
    current = pdf_options_from_tex(tex)
    current.update({key: value for key, value in (options or {}).items()
                    if key in PDF_OPTION_VALUES
                    and value in PDF_OPTION_VALUES[key]})
    tex = re.sub(
        r'(\\documentclass)(?:\[[^\]]*\])?(\{article\})',
        lambda match: (f'{match.group(1)}[{current["size"]},'
                       f'{current["paper"]}]{match.group(2)}'),
        tex, count=1)

    def replace_package(match):
        parts = [part.strip() for part in (match.group(1) or '').split(',')
                 if part.strip()]
        parts = [part for part in parts
                 if not part.startswith('font=') and part != 'diagn']
        if current['font'] != 'cm':
            parts.append(f'font={current["font"]}')
        if current['diagn'] == 'on':
            parts.append('diagn')
        return (f'\\usepackage[{",".join(parts)}]{{egor}}' if parts
                else r'\usepackage{egor}')

    return EGOR_PACKAGE_RE.sub(replace_package, tex, count=1)

# TeX Live 2025-11 убрал \tbl_save_outer_table_cols: из ядра, а bidi
# (xelatex, его подтягивает egor) всё ещё вставляет вызов в \@@array.
# Без заглушки падают array/tabular/cases — в том числе формулы систем
# в \plaintext после импорта Word/TeX. Определяем команду, только если
# её нет: на старых ядрах оставляем настоящую реализацию.
ARRAY_BIDI_SHIM = (
    '\\ExplSyntaxOn\n'
    '\\cs_if_exist:NF \\tbl_save_outer_table_cols:\n'
    '  {\\cs_gset_eq:NN \\tbl_save_outer_table_cols: \\scan_stop:}\n'
    '\\ExplSyntaxOff'
)

# egor складывает всю очередь в один figure: сотня чертежей выходит за
# страницу без Overfull. Разрешаем переносы между рядами, сохраняя подписи.
BREAKABLE_PICTURES = r'''
\makeatletter
\renewcommand{\egor@fitpic}[1]{%
  \sbox{\egor@picbox}{\includegraphics{#1}}%
  \ifdim\wd\egor@picbox>\linewidth
    \includegraphics[width=\linewidth,height=.8\textheight,keepaspectratio]{#1}%
  \else
    \ifdim\ht\egor@picbox>.8\textheight
      \includegraphics[width=\linewidth,height=.8\textheight,keepaspectratio]{#1}%
    \else\usebox{\egor@picbox}\fi
  \fi
}
\patchcmd{\egor@emitpicaux}{\\[3mm]}{\par\vspace{3mm}\noindent}{}{
  \PackageError{egormath}{Unsupported egor picture rows}{Update the picture adapter}}
\NewCommandCopy{\egorOriginalFlushpics}{\flushpics}
\RenewDocumentCommand{\flushpics}{O{0}}{%
  \begingroup
  \renewenvironment{figure}[1][]{\par\noindent\ignorespaces}{\unskip\par}%
  \egorOriginalFlushpics[#1]%
  \endgroup
}
\makeatother
'''


# Сохраняем обычную сигнатуру task для обратного импорта .tex: меняется
# только способ печати следующего короткого учительского задания.
KEEP_SHORT_ANSWER = r'''
\NewCommandCopy{\egorOriginalTask}{\task}
\NewDocumentCommand{\egorCompactTask}{m m +m O{} O{} O{}}{%
  \egorOriginalTask{#1}{0}{%
    \begin{minipage}[t]{\linewidth}%
    #3\par\ans{#5}\par\resh{#6}%
    \end{minipage}\par}%
  \answer{#5}%
  \let\task\egorOriginalTask
}
\newcommand{\egorKeepAnswer}{\let\task\egorCompactTask}
'''


# Короткий ответ сохраняет естественную ширину; длинный переносится внутри
# рамки или ячейки таблицы ответов. varwidth набирает содержимое один раз:
# измерение с последующим повторным набором удваивало счётчики и метки.
# egor запрещает разрывы внутри формул глобально. В длинном ответе
# возвращаем стандартные штрафы TeX, чтобы формулы помещались в ячейку.
WRAPPING_ANSWERS = r'''
\RequirePackage{varwidth}
\newlength{\egorMathAnswerWidth}
\newcommand{\egorMathAnswer}[1]{%
  \begingroup
  \setlength{\egorMathAnswerWidth}{\dimexpr\linewidth-2\fboxsep-2\fboxrule\relax}%
  \begin{varwidth}[t]{\egorMathAnswerWidth}%
    \raggedright\relpenalty=500\binoppenalty=700 #1%
  \end{varwidth}%
  \endgroup
}
% Ответ с выносной формулой или окружением занимает ширину рамки/ячейки.
\newcommand{\egorMathAnswerBlock}[1]{%
  \begingroup
  \setlength{\egorMathAnswerWidth}{\dimexpr\linewidth-2\fboxsep-2\fboxrule\relax}%
  \parbox[t]{\egorMathAnswerWidth}{\raggedright\relpenalty=500\binoppenalty=700 #1}%
  \endgroup
}
% Подпункты не запираем в общую рамку или одну строку longtable:
% каждая часть получает собственную рамку/строку с тем же номером задачи.
% Разделяем токены до набора, без раскрытия содержимого ответов.
\newcommand{\egorAnswerSeparator}{\par}
\makeatletter
\NewCommandCopy{\egorOriginalRecordAnswer}{\egor@recordanswer}
\ExplSyntaxOn
\seq_new:N \l__egormath_answer_parts_seq
\RenewDocumentCommand{\ans}{m}{%
  \ifbool{ans}{%
    \group_begin:
    \seq_set_split:Nnn \l__egormath_answer_parts_seq {\egorAnswerSeparator} {#1}
    \seq_map_inline:Nn \l__egormath_answer_parts_seq
      {\ifblank{##1}{}{\par\cfbox{black}{##1}}}
    \group_end:
  }{}%
}
\renewcommand{\egor@recordanswer}[2]{%
  \group_begin:
  \seq_set_split:Nnn \l__egormath_answer_parts_seq {\egorAnswerSeparator} {#2}
  \seq_map_inline:Nn \l__egormath_answer_parts_seq
    {\egorOriginalRecordAnswer{#1}{##1}}
  \group_end:
}
\ExplSyntaxOff
\makeatother
'''

# Выносная математика и окружения не набираются в LR-боксе \shortstack.
DISPLAY_ANSWER_RE = re.compile(r'\\\[|\$\$|\\begin\{|\\item\b')

# Метки подпунктов как у \asbuk (без ё, й, ъ, ы, ь) — для сводного ответа
CYRILLIC_LABELS = 'абвгдежзиклмнопрстуфхцчшщэюя'


def _opt(content):
    """Опциональный аргумент [..]; фигурные скобки защищают ']' внутри."""
    return '[{%s}]' % content


def subitem_label(index):
    """Метка подпункта по позиции в листке (перенумерация заново)."""
    if index < len(CYRILLIC_LABELS):
        return CYRILLIC_LABELS[index]
    return str(index + 1)


def _for_task_opt(text):
    """Готовит текст для опционального аргумента \\task.

    Аргумент не \\long: пустая строка (\\par) его обрывает. \\mbox{}\\\\
    даёт перенос и после display-формулы (иначе «no line here to end»).
    """
    return re.sub(r'\n\s*\n+', r' \\mbox{}\\\\ ', text.strip())


def _join_labeled(parts, wrapper='stack'):
    """Склеивает куски ответа/решения, каждый на своей строке.

    Голый \\\\ в answers=table завершает строку таблицы пакета egor.
    Ответы оборачиваем с учётом ширины рамки или ячейки таблицы.
    Решения с абзацами и display-формулами должны переноситься по страницам.
    """
    if not parts:
        return ''
    if wrapper == 'flow':
        return ' \\mbox{}\\\\ '.join(parts)
    blocks = []
    for part in parts:
        command = ('egorMathAnswerBlock' if DISPLAY_ANSWER_RE.search(part)
                   else 'egorMathAnswer')
        blocks.append('\\%s{%s}' % (command, part))
    return ' \\egorAnswerSeparator '.join(blocks)


def _combined_answer(task, subitems):
    """Общий ответ задачи + ответы выбранных подпунктов (каждый с новой строки)."""
    def content(owner):
        text = owner.effective_answer_latex
        indices = set(TASKPIC_REF_RE.findall(text))
        if indices and not TASKPIC_REF_RE.sub('', text).strip(' \n.;'):
            text = ('См. рисунок.' if len(indices) == 1 else 'См. рисунки.') + text
        return _for_task_opt(text)

    parts = []
    if task.effective_answer_latex:
        parts.append(content(task))
    parts.extend(
        '%s)~%s' % (subitem_label(i),
                    content(s))
        for i, s in enumerate(subitems) if s.effective_answer_latex
    )
    return _join_labeled(parts, 'stack')


def _combined_solution(task, subitems):
    """Общее решение задачи + решения подпунктов (каждый с новой строки)."""
    # Локальный импорт: веб-представление использует subitem_label.
    from problems.answer_material import solution_texts

    parts = [_for_task_opt(text) for text in solution_texts(task)]
    for index, subitem in enumerate(subitems):
        texts = solution_texts(subitem)
        for number, text in enumerate(texts):
            prefix = '%s)~' % subitem_label(index) if number == 0 else ''
            parts.append(prefix + _for_task_opt(text))
    text = _join_labeled(parts, 'flow')
    if not text:
        return ''
    # Заголовок остаётся с первой строкой, а само решение может занимать
    # несколько страниц: не запираем его целиком в minipage.
    return '\\mbox{}\\\\* %s' % text


# Ссылка на картинку в тексте задачи: \taskpic{N}, N — номер по порядку
TASKPIC_REF_RE = re.compile(r'\\taskpic\{(\d+)\}')


def _resolve_taskpics(text, filenames, used):
    """Заменяет ссылки \\taskpic{N} на \\taskpic{имя-файла}.

    Ссылки на несуществующие номера убираются молча — так PDF компилируется
    и до загрузки картинок (двухшаговый импорт из .tex).
    """
    def repl(match):
        index = int(match.group(1)) - 1
        if 0 <= index < len(filenames):
            used.add(index)
            return '\\taskpic{%s}' % filenames[index]
        return ''
    return TASKPIC_REF_RE.sub(repl, text)


def _taskpic_command(name, sub_labels=None):
    """\\taskpic для тела задачи; у рисунка подпункта — подпись с буквой.

    Сам \\taskpic внутри подпункта egor подписал бы «К задаче 6б», но ссылки
    переносятся в тело (см. task_to_tex), где буква теряется. Поэтому номер
    задают явно: \\taskpic[\\arabic{enumi}б]{файл} — egor раскрывает
    опциональный аргумент через \\edef, и \\arabic{enumi} даёт номер текущей
    задачи. Рисунок к нескольким подпунктам: «К задаче 6б, в».
    """
    if not sub_labels:
        return '\\taskpic{%s}' % name
    return '\\taskpic[\\arabic{enumi}%s]{%s}' % (', '.join(sub_labels), name)


def _keep_choice_statement(body):
    """Не отделяет систему/коэффициенты от вариантов ответа и их рисунков."""
    is_system = body.startswith('Укажите решение системы неравенств')
    is_inequality = body.startswith(('Укажите решение неравенства',
                                    'Укажите неравенство, решение которого'))
    is_linear = body.startswith('На рисунках изображены графики функций вида')
    is_graph_match = ('Установите соответствие' in body.split('\n\n',1)[0]
                      and 'А & Б & В' in body)
    if not (is_system or is_inequality or is_linear or is_graph_match):
        return body
    # Неразобранная OCR-склейка с несколькими кадрами может быть длиннее
    # страницы. Её нельзя запирать целиком в minipage до разделения.
    if len(re.findall(r'\\taskpic\{[^{}]+\}', body)) > 1:
        return body
    if r'\taskpic{' not in body and not all(f'{n})' in body for n in range(1, 5)):
        return body
    # Полоса вариантов должна занимать строку возле условия, иначе egor
    # сжимает её рядом с другими рисунками в общей очереди в конце листка.
    body = re.sub(r'\\taskpic\{([^{}]+)\}(?:\s*\\\\)*',
                  lambda m: (r'\par\noindent\includegraphics'
                             r'[width=.9\linewidth,height=.45\textheight,keepaspectratio]'
                             '{' + m[1] + r'}\par'), body)
    return '\\begin{minipage}[t]{\\linewidth}\n' + body + '\n\\end{minipage}'


def task_to_tex(item, variant='teacher', *, statement=None, common_indices=()):
    """\\task{звёзды}{колонки}{условие}[подпункты][ответ][решение]

    Работает от элемента листка: звёзды/колонки — с учётом переопределений,
    подпункты — только выбранные (пустой выбор = все).
    """
    task = item.task
    subitem_objs = item.selected_subitems()
    filenames = [image.filename for image in task.images.all()]
    body_used = set()
    body = _resolve_taskpics((task.text_latex if statement is None else statement).strip(), filenames, body_used)
    used = set(body_used) | set(common_indices)
    sub_texts = []
    deferred_pics = set()
    # Номер картинки -> буквы подпунктов, где она упомянута
    # (буквы — по позиции среди выбранных, как в сводном ответе).
    pic_subitems = {}
    for sub_index, subitem in enumerate(subitem_objs):
        subitem_used = set()
        sub_text = _resolve_taskpics(
            subitem.text_latex.strip(), filenames, subitem_used)
        # Пакет egor не выводит \\taskpic из опционального
        # аргумента подпунктов, поэтому переносим ссылки в тело.
        sub_text = re.sub(r'\s*\\taskpic\{[^{}]+\}', '', sub_text)
        for i in subitem_used:
            pic_subitems.setdefault(i, []).append(subitem_label(sub_index))
        deferred_pics.update(subitem_used)
        used.update(subitem_used)
        sub_texts.append(sub_text)
    # Пунктуация подпунктов: «;» между пунктами, «.» после последнего
    # (в базе тексты хранятся без знака препинания на конце)
    sub_lines = []
    for i, text in enumerate(sub_texts):
        punct = '.' if i == len(sub_texts) - 1 else ';'
        if text and text[-1] not in ';.!?:':
            text += punct
        sub_lines.append('\\item %s' % text)
    # Без подпунктов колонки обнуляются: \columned{0} печатает только
    # условие, а columns>=1 с пустым списком падают на «missing \item»
    # (пустой [{}] всё равно передаётся, когда дальше идёт ответ).
    # С подпунктами наоборот: columns=0 (значение по умолчанию у задачи,
    # в т.ч. у всех импортированных) заставил бы egor молча выбросить
    # подпункты из PDF — печатаем их хотя бы одной колонкой.
    columns = max(item.effective_columns, 1) if sub_lines else 0
    subitems = '\n'.join(sub_lines)
    answer = _combined_answer(task, subitem_objs)
    answer_used = set()
    answer = _resolve_taskpics(answer, filenames, answer_used)
    answer = re.sub(r'\s*\\taskpic\{[^{}]+\}', '', answer)
    # Рисунок из ответа нельзя переносить в ученическое условие: иначе
    # даже скрытый пакетом egor ответ раскроет часть материала.
    if variant != 'student':
        deferred_pics.update(answer_used)
    used.update(answer_used)
    solution = _combined_solution(task, subitem_objs)
    solution_used = set()
    solution = _resolve_taskpics(solution, filenames, solution_used)
    solution = re.sub(r'\s*\\taskpic\{[^{}]+\}', '', solution)
    # Решения видны только в teacher-варианте. В answers/student их
    # изображения также не должны оказываться в основном теле задачи.
    if variant == 'teacher':
        deferred_pics.update(solution_used)
    used.update(solution_used)
    # Скрытый AI-вариант не делает свой рисунок бесхозным. Резервируем
    # ссылки всех материалов, но печатаем только выбранные выше.
    from problems.task_images import material_indices
    used.update(material_indices(task))
    for subitem in task.subitems.all():
        used.update(material_indices(subitem))
    # Рисунки, на которые ссылаются только невыбранные подпункты, в листок
    # не попадают: самого подпункта в листке нет.
    selected_ids = {s.pk for s in subitem_objs}
    unselected_refs = set()
    all_subitems = getattr(item, 'all_subitems', True)
    for subitem in ([] if all_subitems else task.subitems.all()):
        if subitem.pk not in selected_ids:
            for text in (subitem.text_latex, subitem.effective_answer_latex,
                         subitem.effective_solution_latex):
                _resolve_taskpics(text or '', filenames, unselected_refs)
    # Рисунки из optional-аргументов и рисунки без ссылки
    # выводим один раз в основном теле задачи.
    for i, name in enumerate(filenames):
        if i not in used and i in unselected_refs:
            continue
        if ((i in deferred_pics and i not in body_used)
                or i not in used):
            body += '\n' + _taskpic_command(name, pic_subitems.get(i))
    body = _keep_choice_statement(body)
    short_answer = (variant == 'teacher' and answer and not solution and not sub_lines
                    and len(body) < 400 and r'\begin' not in body and r'\taskpic' not in body)
    parts = [
        '\\task{%d}{%d}{%%\n%s%%\n}' % (
            item.effective_stars, columns, body),
    ]
    # Хвостовые пустые аргументы опускаем, промежуточные передаём пустыми
    tail = []
    if solution:
        tail = [subitems, answer, solution]
    elif answer:
        tail = [subitems, answer]
    elif subitems:
        tail = [subitems]
    for value in tail:
        parts.append(_opt(value))
    result = ''.join(parts)
    if short_answer:
        result = '\\egorKeepAnswer\n' + result
    return result


# Команды egor для стилей текстового элемента (WorksheetItem.text_style)
TEXT_STYLE_COMMANDS = {
    'plain': 'plaintext',
    'rule': 'ruletext',
    'light': 'lighttext',
    'memo': 'memotext',
}


def text_to_tex(item):
    """Произвольный текст между задачами — \\plaintext/\\ruletext/… egor."""
    command = TEXT_STYLE_COMMANDS.get(item.text_style, 'plaintext')
    return '\\%s{%%\n%s%%\n}' % (command, item.text_latex.strip())


def rubric_to_tex(item):
    """Элемент-рубрика — \\rubr{...}[пояснение]; сам открывает список."""
    tex = '\\rubr{%s}' % item.rubric.strip()
    if item.rubric_note.strip():
        tex += _opt(item.rubric_note.strip())
    return tex


def _drop_empty_rubrics(items):
    """Убирает рубрики, после которых до следующей нет задач и текста.

    \\rubr открывает enumerate: если все задачи рубрики скрыты, LaTeX
    падает на «perhaps a missing \\item». Текстовый элемент после
    пустой рубрики оставляем — для него уже есть \\item[].
    """
    kept = []
    i = 0
    n = len(items)
    while i < n:
        item = items[i]
        if item.is_rubric:
            has_content = False
            for nxt in items[i + 1:]:
                if nxt.is_rubric:
                    break
                if nxt.task_id or nxt.is_text:
                    has_content = True
                    break
            if not has_content:
                i += 1
                continue
        kept.append(item)
        i += 1
    return kept


def worksheet_to_tex(worksheet, variant='student', exclude_ids=None):
    """exclude_ids — pk элементов, скрытых для конкретной ссылки/ученика."""
    exclude_ids = exclude_ids or set()
    options = VARIANT_OPTIONS[variant]
    usepackage = ('\\usepackage[%s]{egor}' % options) if options \
        else '\\usepackage{egor}'
    items = _drop_empty_rubrics([
        item for item in worksheet.ordered_items()
        if item.pk not in exclude_ids
    ])
    has_images = any(item.task_id and item.task.images.all() for item in items)

    lines = [
        '\\documentclass[a5paper,10pt]{article}',
        usepackage,
        ARRAY_BIDI_SHIM,
        BREAKABLE_PICTURES if has_images else '',
        KEEP_SHORT_ANSWER,
        WRAPPING_ANSWERS,
        # Не оставляем первую или последнюю строку абзаца на другой странице.
        r'\clubpenalty=10000\widowpenalty=10000',
        '',
        '\\begin{document}',
    ]

    bighead = '\\bighead{%s}{%s}{%s}' % (
        escape_latex(worksheet.title),
        escape_latex(worksheet.grade_label),
        escape_latex(worksheet.display_author),
    )
    if worksheet.subtitle:
        bighead += _opt(escape_latex(worksheet.subtitle))
    lines.append(bighead)
    lines.append('')

    from .block_presentation import block_presentations
    presentations = block_presentations(items)
    list_open = False
    list_has_item = False
    for item in items:
        if item.is_text:
            lines.append('')
            if list_open and not list_has_item:
                # Текст сразу после \rubr: enumerate уже открыт, но пункта
                # ещё нет — пустой \item[] (нумерацию не сдвигает) не даёт
                # LaTeX упасть на «perhaps a missing \item»
                lines.append('\\item[]')
                list_has_item = True
            lines.append(text_to_tex(item))
            continue
        if item.is_rubric:
            # \rubr сам открывает список задач (или продолжает через resume)
            lines.append('')
            lines.append(rubric_to_tex(item))
            list_open = True
            list_has_item = False
            continue
        if not list_open:
            # Задача до первой рубрики — список стартуем вручную
            lines.append('')
            lines.append('\\begin{enumerate}')
            list_open = True
        lines.append('')
        presentation = presentations.get(item.pk)
        if presentation and presentation.common:
            filenames = [image.filename for image in item.task.images.all()]
            # Общее условие не является шестой задачей и не сдвигает ответы.
            # Рисунки нужны рядом с условием, а не в очереди рисунков задачи.
            # OCR-перенос после картинки лишний: includegraphics ниже уже
            # завершает абзац. Иначе следующий \\\\ падает в вертикальном режиме.
            common_source = re.sub(r'(\\taskpic\{\d+\})\s*(?:\\\\\s*)+',
                                   r'\1\n', presentation.common)
            common = TASKPIC_REF_RE.sub(
                lambda match: ('\n' + r'\par\noindent\includegraphics'
                               r'[width=.85\linewidth,height=.35\textheight,keepaspectratio]'
                               + '{%s}' % filenames[int(match.group(1)) - 1]
                               + r'\par' + '\n'),
                common_source)
            lines.append('\\item[] \\textbf{Общее условие к следующим пяти заданиям.}\\par\n' + common)
        lines.append(task_to_tex(
            item, variant, statement=presentation.text if presentation else None,
            common_indices=presentation.common_indices if presentation else ()))
        list_has_item = True

    if list_open:
        if not list_has_item:
            # Пустой enumerate (рубрика без видимых задач и без текста)
            # всё равно нужно закрыть без ошибки «missing \\item»
            lines.append('\\item[]')
        lines.append('')
        lines.append('\\end{enumerate}')
    if has_images:
        lines.append('')
        # На A5 даже два составных чертежа в ряд уменьшают буквы до 3–4 pt.
        # Выбор делаем в TeX, чтобы он учитывал изменение формата в редакторе.
        lines.append(r'\ifdim\textwidth<160mm\picsperrow{1}\else\picsperrow{2}\fi')
        lines.append('\\flushpics')
    lines.append('')
    lines.append('\\end{document}')
    return '\n'.join(lines)


def tex_hash(tex_content):
    return hashlib.sha256(tex_content.encode('utf-8')).hexdigest()
