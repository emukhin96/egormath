"""Дидактические материалы Феоктистова: работы, варианты, тесты.

Неоднозначные границы ответов требуют сверки; исходный авторский текст
сохраняется в диагностике. Исходный файл не изменяется.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from .textbook_parser import (
    Marker, TaskDraft, apply_imported_math, blocks, clean, finalize_draft_images,
    merge_solutions, normalize_task_images, order_letter_subitems, sections, task_from_block,
)

SOURCE_SHA256 = 'bbaf54d974fd1733f52fb7ff9f378f085bc6b09b597d0132a529abd0d598d971'
FIGURE_13 = 'feoktistov9-figure-13'
WORK_RE = re.compile(
    r'(?im)^[ \t]*(?:(?P<sr>самостоятельная)\s+работа\s*№\s*'
    r'|(?P<kr>контрольная)\s+работа\s*№\s*|[ТT][ЕE][СC][ТT]\s*)'
    r'(?P<number>\d+)\b')
VARIANT_RE = re.compile(
    r'(?i)(?P<prep>Подготовительный\s+вариант)|'
    r'В\s*а\s*р\s*и\s*а\s*н\s*т\s+(?P<number>[123])\b')
FIGURE_RE = re.compile(r'\\begin\{figure\}.*?\\end\{figure\}', re.S)
GRAPHICS_RE = re.compile(r'\\includegraphics\s*(?:\[[^]]*\])?\{([^{}]+)\}')
FIG_REF_RE = re.compile(r'(?i)рис(?:унок|унке|унку|унка|унки|унках|\.)\s*(\d+)')
MATH_RE = re.compile(r'\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|\$[^$]*\$', re.S)
GROUP_NAMES = {'sr': 'Самостоятельные работы', 'kr': 'Контрольные работы', 'test': 'Тесты'}
WORK_NAMES = {'sr': 'Самостоятельная работа', 'kr': 'Контрольная работа', 'test': 'Тест'}


def _headings(text):
    for section in reversed(sections(text)):
        text = text[:section.start] + '\n' + section.title + '\n' + text[section.end:]
    return text


def _work_spans(text):
    matches = list(WORK_RE.finditer(text))
    for i, match in enumerate(matches):
        kind = 'sr' if match['sr'] else 'kr' if match['kr'] else 'test'
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end]
        body = re.split(r'(?m)^\s*(?:САМОСТОЯТЕЛЬНЫЕ РАБОТЫ|КОНТРОЛЬНЫЕ РАБОТЫ|ТЕСТЫ)\s*$', body)[0]
        yield kind, int(match['number']), body


def _variants(text):
    matches = list(VARIANT_RE.finditer(text))
    for i, match in enumerate(matches):
        key = 'prep' if match['prep'] else 'v' + match['number']
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].lstrip(' .\n\t')
        yield key, body


def _task_markers(text):
    """Верхние номера списков и обычных строк; 1) — варианты ответа."""
    pattern = re.compile(
        r'\\(?P<env>begin|end)\{(?P<kind>enumerate|itemize)\}'
        r'|\\setcounter\{enumi\}\{(?P<count>\d+)\}'
        r'|\\item(?:\[(?P<label>[^]]*)\])?'
        r'|(?m:^[ \t]*(?P<plain>\d{1,2})\.\s+(?=[А-ЯA-Z]))')
    stack = []
    count = 0
    result = []
    for match in pattern.finditer(text):
        if match['env']:
            if match['env'] == 'begin':
                stack.append(match['kind'])
                if match['kind'] == 'enumerate' and stack.count('enumerate') == 1:
                    count = 0
            elif stack:
                stack.pop()
        elif match['count'] is not None:
            count = int(match['count'])
        elif match['plain']:
            result.append(Marker(match.start(), match.end(), match['plain']))
        elif match['label'] is not None:
            number = re.fullmatch(r'\s*(\d{1,2})\.\s*', match['label'])
            if number:
                result.append(Marker(match.start(), match.end(), number[1]))
        elif stack and stack[-1] == 'enumerate' and stack.count('enumerate') == 1:
            count += 1
            result.append(Marker(match.start(), match.end(), str(count)))
    return result


def _test_lists(text):
    """Раскрывает OCR-enumerate с вариантами ответа, сохраняя номера задач."""
    def expand(match):
        body = match[1]
        counter = re.search(r'\\setcounter\{enumi\}\{(\d+)\}', body)
        number = int(counter[1]) if counter else 0
        body = re.sub(r'\\setcounter\{enumi\}\{\d+\}', '', body)
        def item(found):
            nonlocal number
            number += 1
            tail = body[found.end():].lstrip()
            # Условия тестов начинаются с русской формулировки.
            suffix = '.' if re.match(r'[А-ЯЁ]', tail) else ')'
            return '\n' + str(number) + suffix + ' '
        return re.sub(r'\\item(?!\[)', item, body)
    return re.sub(r'\\begin\{enumerate\}(.*?)\\end\{enumerate\}', expand, text, flags=re.S)


def _strip_lists(text):
    text = re.sub(r'\\(?:begin|end)\{(?:enumerate|itemize)\}', '', text)
    text = re.sub(r'\\setcounter\{[^{}]+\}\{\d+\}', '', text)
    return re.sub(r'\\item\[\s*\]', '', text)


def _figures(text, known):
    figures = {}

    def remove(match):
        blob = match[0]
        graphic = GRAPHICS_RE.search(blob)
        caption = re.search(r'\\caption\{\s*Рис\.\s*(\d+)', blob)
        if graphic and caption:
            number = int(caption[1])
            # В данном скане рис. 15 дважды подписан как 16.
            if known and graphic[1].endswith('-126_295_574_664_728'):
                number = 15
            if number in figures and figures[number] != graphic[1]:
                raise ValueError(f'Неоднозначная подпись рисунка {number}')
            figures[number] = graphic[1]
        variant = VARIANT_RE.search(blob)
        return '\n' + (variant[0] if variant else '') + '\n'

    text = FIGURE_RE.sub(remove, text)
    if known:
        figures[13] = FIGURE_13
    return text, figures


def _title(prefix):
    prefix = prefix.split('ОСНОВНЫЕ СВЕДЕНИЯ')[0]
    prefix = re.sub(r'^\s*Глава\s+\d+\.\s*', '', prefix)
    # Первые строки — название; последующая проза — теория.
    parts = [p.strip() for p in prefix.replace('\\\\', '\n').splitlines() if p.strip()]
    result = []
    for part in parts:
        if len(part) > 200 or part.startswith(('\\begin', 'Определение', 'Функция')):
            break
        result.append(part)
        if len(' '.join(result)) > 140:
            break
    return clean(' '.join(result))[:200]


def _test_choices(text):
    """Возвращает метки выбора из формул OCR и нумерует список чисел."""
    text = re.sub(r'(?m)^\s*з\)', '3)', text)
    text = re.sub(r'(?m)^(\s*)\\\(([1-4])\)', r'\1\2) \\(', text)
    inline = re.search(r'Какое из чисел\s*\\\(([^{}]+?)\\\)', text)
    if inline:
        values = [v.strip() for v in inline[1].split(';')]
        if len(values) == 4:
            text += '\n' + r'\\'.join(
                f'{i}) '+r'\('+v+r'\)' for i, v in enumerate(values, 1))
    return text


def _answer_markers(text, allowed):
    """Не режет формулы по цифрам. Сомнительные склейки остаются для сверки."""
    spans = [(m.start(), m.end()) for m in MATH_RE.finditer(text)]
    # Сохраняем смещения: merge_solutions получает исходный текст.
    scan = re.sub(r'\\\\(?=\s*\n)', '  ', text)
    result = []
    previous = 0
    for match in re.finditer(r'(?<![\w,;+-])(\d{1,2})\s*\.\s*(?!\d)', text):
        number = int(match[1])
        if str(number) not in allowed or number <= previous:
            continue
        if any(lo <= match.start() < hi for lo, hi in spans):
            continue
        before = scan[:match.start()].rstrip()
        if before and not before.endswith(('.', r'\)', r'\]', '\n')):
            continue
        # Номер без тела — обычно сам числовой ответ предыдущего задания.
        if re.match(r'\d+\s*\.', text[match.end():]):
            continue
        result.append(Marker(match.start(), match.end(), str(number)))
        previous = number
    return result


def _known_answer_work(kind, number, body):
    """Границы испорченных OCR-вариантов, сверенные на печатных с. 168–170."""
    if kind != 'sr':
        return body
    if number == 12:
        # OCR вписал ответы № 5–6 и заголовки внутрь строк систем № 4.
        return r'''
Подготовительный вариант.
1. а) не является; б) является. 2. а) не пересекает; б) пересекает.
4. \(\begin{cases}2x+3y\geqslant6\\x-2y\geqslant-4\\3x+y\leqslant9\end{cases}\).
5. \(8\). 6. При \(b<8\).
Вариант 1.
1. а) является; б) является. 2. а) не пересекает; б) пересекает.
4. \(\begin{cases}x+3y\geqslant-3\\2x+y\leqslant-1\\x-2y\geqslant-3\end{cases}\).
5. \(8\). 6. При \(b>2\).
Вариант 2.
1. а) является; б) является. 2. а) не пересекает; б) пересекает.
4. \(\begin{cases}3x-2y\geqslant-6\\2x+y\leqslant3\\x-3y\leqslant-2\end{cases}\).
5. \(4\). 6. При \(b<18\).
Вариант 3.
1. а) не является; б) не является. 2. а) не пересекает; б) пересекает.
4. \(\begin{cases}-x+2y\geqslant2\\x+y\leqslant1\\-2x+y\leqslant4\end{cases}\).
5. \(4\). 6. При \(b<16\).
'''
    if number == 14:
        start = body.index(r'В ар и aн \(\mathrm{T} 2.')
        end = body.index('В ариант 3.', start)
        return body[:start] + r'''
Вариант 2. 1. \(14-14\sqrt{2}\). 2. \(-285\).
3. \(26; a_{26}=0,1\). 4. \(8,5;13;17,5\). 5. \(1;6\).
6. \(\frac{14}{25}\). 7. \(465718\). 8. При \(n=2\).
''' + body[end:]
    if number == 17:
        return body.replace('В а - риант 3.', 'Вариант 3.')
    return body


def _answer_groups(text, known):
    groups, originals = {}, {}
    for kind, number, work in _work_spans(_headings(text)):
        work = work.split(r'\begin{table}')[0]
        repaired = _known_answer_work(kind, number, work) if known else work
        if repaired != work:
            originals[f'{kind}/{number:02d}'] = work
        for variant, body in _variants(repaired):
            key = (kind, number, variant)
            if key in groups:
                raise ValueError(f'Повторная группа ответов: {kind}/{number:02d}/{variant}')
            groups[key] = body
    return groups, originals


def _answer_fields(task):
    return [task.author_answer_latex, task.author_solution_latex] + [
        value for item in task.subitems for value in
        (item.author_answer_latex, item.author_solution_latex)]


def _repair_answer_labels(task):
    """Возвращает скобку метки за пределы формулы после общего OCR-healing."""
    for item in [task, *task.subitems]:
        for name in ('author_answer_latex', 'author_solution_latex'):
            value = getattr(item, name)
            value = re.sub(r'(?<![\w\\])([а-яa-d])\s*\$(\\displaystyle\s*)?\)\s*',
                           lambda m: m[1] + ') $' + (m[2] or ''), value)
            setattr(item, name, value)


def _test_answers(text):
    result = {}
    test_number = None
    for row in text.split(r'\\'):
        if '&' not in row:
            continue
        cells = row.split('&')
        match = re.search(r'[ТT]\s*(\d+|З)\b', cells[0])
        if match:
            test_number = 3 if match[1] == 'З' else int(match[1])
        if test_number is None or len(cells) != 8:
            continue
        variant = re.search(r'Вариант\s*([12])', cells[1])
        values = [v.strip() for v in cells[2:]]
        if variant and all(re.fullmatch('[1-4]', v) for v in values):
            for num, value in enumerate(values, 1):
                key = f'test/{test_number:02d}/v{variant[1]}/{num:03d}'
                if key in result:
                    raise ValueError(f'Повторный ключ тестового ответа: {key}')
                result[key] = value
    return result


def _known_answer_repairs(task):
    """Сверенные по PDF ответы скана 2018 года (печатные с. 162, 175)."""
    if task.external_id == 'sr/01/v3/001':
        for item in task.subitems:
            if item.label == 'б':
                item.author_answer_latex = r'$[-5,75]=-6,\{-5,75\}=0,25$'
    elif task.external_id == 'kr/01/v2/002':
        task.author_answer_latex = r'При $a=4$.'


def _unbalanced_math(text):
    remainder = MATH_RE.sub('', text)
    return bool(re.search(r'\\[()\[\]]|(?<!\\)\$', remainder))


def parse_feoktistov(source):
    known = hashlib.sha256(source.encode()).hexdigest() == SOURCE_SHA256
    answer_heading = re.search(r'\\section\*?\{\s*ОТВЕТЫ\s*\}', source, re.I)
    if not answer_heading:
        raise ValueError('Не найден раздел ответов Феоктистова')
    task_text, answer_text = source[:answer_heading.start()], source[answer_heading.end():]
    task_text = re.split(r'\\section\*?\{КОММЕНТАРИЙ ДЛЯ УЧИТЕЛЯ\}', task_text)[0]
    if known:
        task_text = task_text.replace(
            r'\section*{САМОСТОЯТЕЛЬНЫЕ РАБОТЫ}',
            r'\section*{САМОСТОЯТЕЛЬНЫЕ РАБОТЫ}' + '\n'
            + r'\section*{САМОСТОЯТЕЛЬНАЯ РАБОТА № 1 Свойства функций}', 1)
    task_text, figures = _figures(task_text, known)
    task_text = _headings(task_text)
    answer_groups, original_answer_works = _answer_groups(answer_text, known)
    test_answers = _test_answers(answer_text)
    tasks = []
    seen = set()
    counts = {}
    raw_answers = {}
    issues = []
    missing_answers = []
    missing_by_work = Counter()
    answer_anomalies = {}
    for kind, number, work in _work_spans(task_text):
        first_variant = VARIANT_RE.search(work)
        if not first_variant:
            issues.append(f'{kind}/{number:02d}: нет вариантов')
            continue
        topic = _title(work[:first_variant.start()])
        work_title = f'{WORK_NAMES[kind]} № {number}' + (f'. {topic}' if topic else '')
        for variant, body in _variants(work):
            group = f'{kind}/{number:02d}/{variant}'
            variant_title = 'Подготовительный вариант' if variant == 'prep' else f'Вариант {variant[1:]}'
            path = [GROUP_NAMES[kind], work_title, variant_title]
            if kind == 'test':
                body = _test_lists(body)
            markers = _task_markers(body)
            numbers = [int(m.external_id) for m in markers]
            counts[group] = numbers
            if numbers != list(range(1, max(numbers, default=0) + 1)):
                issues.append(f'{group}: проверить номера {numbers}')
            group_tasks = []
            common = ''
            common_match = re.search(
                r'На рисунке\s+(\d+).*?упражнения\s*№\s*2\s*[-–—]\s*5\.', body, re.S)
            if common_match:
                common = common_match[0].split('Пользуясь')[0].strip()
            for marker, block in blocks(body, markers):
                key = f'{group}/{int(marker.external_id):03d}'
                if key in seen:
                    raise ValueError(f'Повторный номер Феоктистова: {key}')
                seen.add(key)
                block = _strip_lists(block)
                block = re.sub(r'\\hspace\{0pt\}', '', block)
                block = block.replace(r'\\[0pt]', r'\\')
                block = re.sub(r'На рисунке\s+\d+.*?упражнения\s*№\s*2\s*[-–—]\s*5\.', '', block, flags=re.S)
                block = re.sub(r'(?im)^\s*Рис\.\s*\d+\s*$', '', block)
                if common and 2 <= int(marker.external_id) <= 5:
                    block = common + '\n' + block
                referenced = list(dict.fromkeys(int(m[1]) for m in FIG_REF_RE.finditer(block)))
                images = [figures.get(n, f'feoktistov-figure-{n}-missing') for n in referenced]
                for image in images:
                    block += '\n' + r'\includegraphics{' + image + '}'
                if kind == 'test':
                    block = _test_choices(block)
                    if known and key == 'test/02/v1/001':
                        block = block.replace(r'3)  \(5 x^{5}', r'4)  \(5 x^{5}')
                    # Цифровые варианты ответа остаются в условии задачи.
                    block = re.sub(r'\\item\[([^]]+)\]', r'\1 ', block)
                    text, image_names = normalize_task_images(block)
                    task = TaskDraft(key, marker.external_id, path, group, work_title,
                                     topic, apply_imported_math(clean(text)), images=image_names)
                    answer = test_answers.get(key, '')
                    task.author_answer_latex = answer
                    task.answer_mask = ('{{choice: ' + '|'.join(
                        ('*' if str(n) == answer else '') + str(n) for n in range(1, 5)) + '}}') if answer else ''
                    if not answer:
                        task.warnings.append('Не найден табличный ключ теста')
                    labels = re.findall(r'(?m)(?:^|\\\\)[ \t]*([1-4])\)', task.text_latex)
                    if sorted(labels) != ['1', '2', '3', '4']:
                        task.warnings.append('Сверить четыре варианта ответа теста с PDF')
                else:
                    task = task_from_block(Marker(0, 0, key), block, path)
                    task.source_number = marker.external_id
                    task.collection_key = group
                    task.collection_title = work_title
                    task.topic_original = topic
                    task.subitems = order_letter_subitems(task.subitems)
                task.grade_band_codes = ['GRADE_9']
                for n in referenced:
                    if n not in figures:
                        task.warnings.append(f'Не найден рисунок {n}: восстановить из PDF')
                group_tasks.append(task)
            if kind != 'test':
                answer = answer_groups.get((kind, number, variant), '')
                if not answer.strip():
                    issues.append(f'{group}: пустая группа авторских ответов')
                # Исходный абзац всегда доступен для проверки границ ответов.
                raw_answers[group] = answer
                local = _answer_markers(answer, {t.source_number for t in group_tasks})
                mapped = [Marker(m.start, m.end, f'{group}/{int(m.external_id):03d}') for m in local]
                merge_solutions(group_tasks, answer, lambda _: mapped, missing_ok=True)
                raw_blocks = {m.external_id: block for m, block in blocks(answer, mapped)}
                for task in group_tasks:
                    task.warnings.append('Сверить границы авторского ответа с PDF Феоктистова')
                    raw_block = raw_blocks.get(task.external_id, '')
                    suspects = sorted({int(m[1]) for m in re.finditer(
                        r'(?<![\w,;+-])(\d{1,2})\s*\.\s*(?!\d)', raw_block)
                        if int(task.source_number) < int(m[1]) <= max(numbers, default=0)})
                    if suspects:
                        task.warnings.append('В ответе возможны следующие номера: '
                                             + ', '.join(map(str, suspects)))
                    if re.search(r'В\s*[аa]\s*(?:р\s*и|[-}]\s*р)', raw_block):
                        task.warnings.append('В ответе остался обломок заголовка варианта')
                    _repair_answer_labels(task)
            for task in group_tasks:
                if known:
                    _known_answer_repairs(task)
                if kind != 'test' and not any(_answer_fields(task)):
                    missing_answers.append(task.external_id)
                    missing_by_work[f'{kind}/{number:02d}'] += 1
                    task.warnings.append('Не найден авторский ответ: сверить с PDF '
                                         '(возможна задача без ответа)')
                fields = [task.text_latex, task.author_answer_latex, task.author_solution_latex]
                fields.extend(value for item in task.subitems for value in
                              (item.text_latex, item.author_answer_latex, item.author_solution_latex))
                if any(_unbalanced_math(value) for value in fields):
                    task.warnings.append('Незакрытые разделители формулы: сверить с PDF')
                finalize_draft_images(task)
                specific = [w for w in task.warnings if w !=
                            'Сверить границы авторского ответа с PDF Феоктистова']
                if specific:
                    answer_anomalies[task.external_id] = specific
                tasks.append(task)
    if known:
        expected = {f'{kind}/{number:02d}/{variant}'
                    for kind, limit in (('sr', 25), ('kr', 7), ('test', 13))
                    for number in range(1, limit + 1)
                    for variant in (('v1', 'v2') if kind == 'test' else ('prep', 'v1', 'v2', 'v3'))}
        issues.extend(f'Нет варианта: {key}' for key in sorted(expected - counts.keys()))
    for task in tasks:
        group = task.collection_key
        if kind_issues := [issue for issue in issues if group in issue]:
            task.warnings.extend(kind_issues)
            answer_anomalies.setdefault(task.external_id, []).extend(kind_issues)
        if task.external_id.startswith('test/') and counts[group] != list(range(1, 7)):
            task.warnings.append('В варианте теста должно быть шесть вопросов')
    if not tasks:
        raise ValueError('Не найдены работы Феоктистова с вариантами и задачами')
    return tasks, {
        'unique_tasks': len(tasks), 'feoktistov_variant_numbers': counts,
        'feoktistov_structure_issues': issues,
        'feoktistov_raw_answer_groups': raw_answers,
        'feoktistov_original_answer_works': original_answer_works,
        'feoktistov_missing_answer_count': len(missing_answers),
        'feoktistov_missing_answers_by_work': dict(sorted(missing_by_work.items())),
        'feoktistov_missing_answer_ids': missing_answers,
        'feoktistov_answer_anomalies': answer_anomalies,
        'feoktistov_test_answer_count': len(test_answers),
        'feoktistov_known_scan': known,
        'feoktistov_required_recovered_assets': [FIGURE_13] if known else [],
        'duplicate_task_ids': [],
    }
