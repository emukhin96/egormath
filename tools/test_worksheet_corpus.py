#!/usr/bin/env python3
"""Тесты инвентаря и парсеров листков без Django (кроме egor)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
_PUBLIC = TOOLS.parent / 'public_html'
if str(_PUBLIC) not in sys.path:
    sys.path.insert(0, str(_PUBLIC))

from worksheet_corpus.detect import decide_verdict, detect_dialect, grade_from_path
from worksheet_corpus.emit import emit_egor_tex
from worksheet_corpus.latex_scan import (
    TITLE_PROPOSED_WARNING, apply_proposed_title, extract_choice_envs,
    extract_title_guess, find_env_spans, split_alpha_subitems,
    split_top_items, strip_answer_grids, strip_layout_space,
    strip_subitem_punct, title_looks_from_filename)
from worksheet_corpus.cleanup import (
    clean_answer_junk, clean_draft, rewrite_equation_answer)
from worksheet_corpus.classify import (
    exam_codes_from_elements, classify_draft, suggest_topic,
    topic_is_confident)
from worksheet_corpus.subitems import (
    maybe_split_element, split_pile)
from worksheet_corpus.parse import (
    _preserve_review_fields, make_draft, parse_and_store, parse_chem_math,
    parse_enumerate_source, parse_exam_source, parse_flexible_tasks,
    parse_zad_source, preprocess_mathneo, store_failed_draft)
from worksheet_corpus.store import load_draft, save_draft


class DetectTests(unittest.TestCase):
    def test_egor_package(self):
        src = r'\documentclass{article}\usepackage{mathneo}\begin{document}\end{document}'
        self.assertEqual(detect_dialect(src, Path('math6-07-percent.tex')), 'egor')

    def test_enumerate(self):
        src = r'\documentclass{article}\begin{document}\begin{enumerate}\item x\end{enumerate}\end{document}'
        self.assertEqual(detect_dialect(src, Path('oge-16.tex')), 'enumerate')

    def test_chem_math(self):
        src = r'\documentclass{article}\usepackage{chem}\begin{document}\task{a}{b}\end{document}'
        self.assertEqual(detect_dialect(src, Path('math5-vzaim_prost.tex')),
                         'chem-math')

    def test_probsoln_skip(self):
        src = r'\newproblem{v1}{текст}{1}'
        path = Path('matvert8-teorver-komb-task.tex')
        dialect = detect_dialect(src, path)
        self.assertEqual(dialect, 'probsoln')
        verdict, reason = decide_verdict(path, dialect, src, path.name)
        self.assertEqual(verdict, 'skip')
        self.assertIn('probsoln', reason)

    def test_chem_filename_skipped(self):
        src = r'\documentclass{article}\begin{document}\begin{enumerate}\item x\end{enumerate}\end{document}'
        path = Path('chem11-kr1.tex')
        dialect = detect_dialect(src, path)
        verdict, reason = decide_verdict(path, dialect, src, path.name)
        self.assertEqual(verdict, 'skip')
        self.assertEqual(reason, 'химия')

    def test_zad_only_defined_is_enumerate(self):
        src = (
            r'\documentclass{article}\newcommand{\zad}{x}'
            r'\begin{document}\begin{enumerate}\item a\end{enumerate}'
            r'\end{document}')
        self.assertEqual(detect_dialect(src, Path('geom.tex')), 'enumerate')

    def test_copy_filename_skipped(self):
        src = r'\documentclass{article}\begin{document}\begin{enumerate}\item x\end{enumerate}\end{document}'
        path = Path('math08-alg_podg (2).tex')
        dialect = detect_dialect(src, path)
        verdict, reason = decide_verdict(path, dialect, src, path.name)
        self.assertEqual(verdict, 'skip')
        self.assertIn('копия', reason)

    def test_math_filename_grade(self):
        path = Path('/tmp/6 класс/math11-trigonom.tex')
        self.assertEqual(grade_from_path(path, 6), 11)
        self.assertEqual(
            grade_from_path(Path('/tmp/6 класс/6-prac-logic.tex'), 6), 6)

    def test_exam_math_review(self):
        src = r'\documentclass{exam}\begin{document}\begin{questions}\question 1\end{questions}\end{document}'
        path = Path('8-kr-final.tex')
        dialect = detect_dialect(src, path)
        self.assertEqual(dialect, 'exam')
        verdict, _ = decide_verdict(path, dialect, src, path.name)
        self.assertEqual(verdict, 'review')


class ParseLegacyTests(unittest.TestCase):
    def test_enumerate_nested(self):
        src = r"""
\documentclass{article}
\begin{document}
\begin{center}\Large{16. Окружность}\end{center}
\begin{enumerate}[1.]
\item Найдите радиус.
\item Решите:
\begin{enumerate}
\item первый;
\item второй.
\end{enumerate}
\end{enumerate}
\end{document}
"""
        parsed = parse_enumerate_source(src)
        self.assertEqual(parsed['header']['title'], '16. Окружность')
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 2)
        self.assertIn('радиус', tasks[0]['text'])
        self.assertEqual(len(tasks[1]['subitems']), 2)
        self.assertIn('первый', tasks[1]['subitems'][0])

    def test_section_mark_is_rubric(self):
        src = r"""
\documentclass{article}
\begin{document}
\begin{center}\Large{Геометрическая вероятность}\end{center}
\begin{chap}
§1. Случайный выбор точки
\end{chap}
\begin{enumerate}[1.]
\item Первая задача.
\end{enumerate}
\begin{chap}
§2. Координатная плоскость
\end{chap}
\begin{enumerate}[1.]
\item Вторая задача.
\end{enumerate}
\end{document}
"""
        parsed = parse_enumerate_source(src)
        rubrics = [el['rubric'] for el in parsed['elements'] if el['kind'] == 'rubric']
        texts = [el for el in parsed['elements'] if el['kind'] == 'text']
        self.assertEqual(rubrics, [
            '§1. Случайный выбор точки',
            '§2. Координатная плоскость',
        ])
        self.assertEqual(texts, [])
        self.assertEqual(
            [el['kind'] for el in parsed['elements']].count('rubric'), 2)

    def test_captioned_images_go_to_numbered_tasks(self):
        src = r"""
\documentclass{article}
\begin{document}
\begin{enumerate}[1.]
\item Первая без рисунка.
\item Вторая без рисунка.
\item Третья про прямоугольник.
\item Четвёртая про окружность.
\begin{center}
\makebox[32mm][c]{\textit{К задаче 3}}
\makebox[32mm][c]{\textit{К задаче 4}}
\par
\includegraphics[width=32mm]{pic1.png}
\includegraphics[width=32mm]{pic2.png}
\end{center}
\end{enumerate}
\end{document}
"""
        parsed = parse_enumerate_source(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 4)
        self.assertEqual(tasks[0]['images'], [])
        self.assertEqual(tasks[1]['images'], [])
        self.assertEqual(tasks[2]['images'], ['pic1.png'])
        self.assertEqual(tasks[3]['images'], ['pic2.png'])
        self.assertNotIn('К задаче', tasks[3]['text'])
        self.assertNotIn('taskpic', tasks[3]['text'])
        self.assertIn('окружность', tasks[3]['text'])

    def test_captioned_images_after_alpha_subitems(self):
        src = r"""
\documentclass{article}
\begin{document}
\begin{enumerate}[1.]
\item Первая без рисунка.
\item Вторая без рисунка.
\item Третья без рисунка.
\item Четвёртая без рисунка.
\item Углы вертикальные. Найдите вероятность того, что точка $X$ лежит:\\
a) внутри хотя бы одного из углов;\\
б) внутри угла $DOC$.
\begin{center}
\makebox[0.22\linewidth][c]{\textit{К задаче 1}}
\makebox[0.22\linewidth][c]{\textit{К задаче 2}}
\makebox[0.22\linewidth][c]{\textit{К задаче 3}}
\makebox[0.22\linewidth][c]{\textit{К задаче 4}}
\par
\includegraphics[width=0.22\linewidth]{pic1.png}
\includegraphics[width=0.22\linewidth]{pic2.png}
\includegraphics[width=0.22\linewidth]{pic3.png}
\includegraphics[width=0.22\linewidth]{pic4.png}
\end{center}
\end{enumerate}
\end{document}
"""
        parsed = parse_enumerate_source(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 5)
        self.assertEqual(
            [el['images'] for el in tasks],
            [['pic1.png'], ['pic2.png'], ['pic3.png'], ['pic4.png'], []])
        self.assertEqual(len(tasks[4]['subitems']), 2)
        self.assertNotIn('К задаче', tasks[4]['text'])
        self.assertNotIn('taskpic', tasks[4]['text'])
        self.assertNotIn('К задаче', ''.join(tasks[4]['subitems']))
        self.assertNotIn('taskpic', ''.join(tasks[4]['subitems']))
        self.assertIn('DOC', tasks[4]['subitems'][1])

    def test_captioned_images_after_enumerate_end(self):
        src = r"""
\documentclass{article}
\begin{document}
\begin{enumerate}[1.]
\item Найдите $x$ на рисунке.
\item Найдите отношение $BD:DC$.
\item Текстовая задача без рисунка.
\end{enumerate}
\begin{center}
\makebox[6cm][c]{\textit{К задаче 1}}\makebox[48mm][c]{\textit{К задаче 2}}
\includegraphics[width=6cm]{pic-class-1.png}
\includegraphics[width=48mm]{pic-class-2.png}
\end{center}
\newpage
\begin{enumerate}[1.]
\item Найдите $x$ на рисунке.
\item Найдите отношение $BD:DC$.
\end{enumerate}
\begin{center}
\makebox[6cm][c]{\textit{К задаче 1}}\makebox[48mm][c]{\textit{К задаче 2}}
\includegraphics[width=6cm]{pic-home-1.png}
\includegraphics[width=48mm]{pic-home-2.png}
\end{center}
\end{document}
"""
        parsed = parse_enumerate_source(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 5)
        self.assertEqual(tasks[0]['images'], ['pic-class-1.png'])
        self.assertEqual(tasks[1]['images'], ['pic-class-2.png'])
        self.assertEqual(tasks[2]['images'], [])
        self.assertEqual(tasks[3]['images'], ['pic-home-1.png'])
        self.assertEqual(tasks[4]['images'], ['pic-home-2.png'])

    def test_title_skips_running_header(self):
        src = r"""
\documentclass{article}
\title{Математическая вертикаль. 7 класс}
\begin{document}
\begin{center}
\Large
{Введение в логику. «Если — то»}
\end{center}
\end{document}
"""
        header = extract_title_guess(src)
        self.assertEqual(header['title'], 'Введение в логику. «Если — то»')

    def test_title_strips_latex(self):
        src = r"""
\documentclass{article}
\begin{document}
\bighead{\par\large Проценты}{7 класс}{Автор}
\end{document}
"""
        header = extract_title_guess(src)
        self.assertEqual(header['title'], 'Проценты')
        self.assertNotIn(r'\par', header['title'])
        self.assertNotIn(r'\large', header['title'])
        commented = extract_title_guess(
            r'\documentclass{article}\begin{document}'
            r'\begin{center}\Large{Диктант №1. \par Точки %\par вертикаль}'
            r'\end{center}\end{document}')
        self.assertEqual(commented['title'], 'Диктант №1. Точки')

    def test_zad_example_and_enumerate_star(self):
        src = r"""
\documentclass{article}
\begin{document}
\zad Укажите верные утверждения.
\begin{enumerate*}%[1)]
\item Первое.
\item Второе.
\end{enumerate*}
\begin{example}
Расставьте стрелочки.
\end{example}
\zad Следующая задача.
\end{document}
"""
        parsed = parse_zad_source(src)
        kinds = [el['kind'] for el in parsed['elements']]
        self.assertEqual(kinds.count('task'), 2)
        self.assertIn('text', kinds)
        first = [el for el in parsed['elements'] if el['kind'] == 'task'][0]
        self.assertEqual(len(first['subitems']), 2)
        self.assertIn('Первое', first['subitems'][0])
        memo = [el for el in parsed['elements'] if el['kind'] == 'text'][0]
        self.assertIn('стрелочки', memo['text'])

    def test_enumerate_not_confused_with_star(self):
        text = r'\begin{enumerate*}\item a\end{enumerate*}'
        self.assertEqual(find_env_spans(text, 'enumerate'), [])
        self.assertEqual(len(find_env_spans(text, 'enumerate*')), 1)

    def test_zad_alpha(self):
        src = r"""
\documentclass{article}
\begin{document}
\Large{Алгебраические дроби}
\zad Сократите дробь: \\
а)~$12ab$; \quad
б)~$3c$.
\end{document}
"""
        parsed = parse_zad_source(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 1)
        self.assertGreaterEqual(len(tasks[0]['subitems']), 2)

    def test_chem_task(self):
        src = r"""
\documentclass{article}
\usepackage{chem}
\begin{document}
\head{Делимость}{Занятие 3}
\task{Докажите, что $n$ делится на 5.}{Указание: последняя цифра.}
\end{document}
"""
        parsed = parse_chem_math(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 1)
        self.assertIn('делится', tasks[0]['text'])
        self.assertIn('Указание', tasks[0]['answer'])

    def test_flexible_one_arg_task(self):
        src = r"""
\documentclass{article}
\usepackage{math}
\begin{document}
\mathhead{Проценты}
\begin{enumerate}
\task{Найдите $10\%$ от 50.}
\dtask{Решите $x+1=2$.}{1}
\end{enumerate}
\end{document}
"""
        parsed = parse_flexible_tasks(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 2)
        self.assertIn('10', tasks[0]['text'])
        self.assertEqual(tasks[1]['answer'], '1')
        enum_parsed = parse_enumerate_source(src)
        self.assertEqual(
            len([el for el in enum_parsed['elements'] if el['kind'] == 'task']), 2)

    def test_exam_questions(self):
        src = r"""
\documentclass{exam}
\begin{document}
\begin{questions}
\question Найдите площадь.
\begin{oneparchoices}
\choice 2
\choice 4
\end{oneparchoices}
\question Решите:
\part $x=1$
\part $x=2$
\end{questions}
\end{document}
"""
        parsed = parse_exam_source(src)
        tasks = [el for el in parsed['elements'] if el['kind'] == 'task']
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]['choices'], ['2', '4'])
        self.assertEqual(tasks[0]['subitems'], [])
        self.assertNotIn('oneparchoices', tasks[0]['text'])
        self.assertGreaterEqual(len(tasks[1]['subitems']), 2)

    def test_enumerate_oge_tag_and_vspace(self):
        src = r"""
\documentclass{article}
\begin{document}
\begin{enumerate}
\item \oge Решите уравнение, используя разложение на множители:
\vspace{10mm}
\begin{enumerate}
\item $x=1$
\item $x=2$
\end{enumerate}
\end{enumerate}
\end{document}
"""
        parsed = parse_enumerate_source(src)
        task = [el for el in parsed['elements'] if el['kind'] == 'task'][0]
        self.assertIn(r'\oge', task['text'])
        self.assertIn('разложение', task['text'])
        self.assertNotIn('vspace', task['text'])
        self.assertEqual(len(task['subitems']), 2)
        from worksheet_corpus.classify import exam_codes_from_elements
        self.assertEqual(
            exam_codes_from_elements(parsed['elements'], 9), ['OGE_2026'])

    def test_exam_oneparcheckboxes_and_grid(self):
        src = r"""
\documentclass{exam}
\begin{document}
\begin{questions}
\question Решите уравнение.
\begin{oneparcheckboxes}
\choice 10;−10
\choice 12;
\choice нет корней
\choice другой ответ
\end{oneparcheckboxes}
\vspace{2mm}\noindent
\begin{tikzpicture}[scale=0.5]
\draw [help lines] (0,0) grid (37,5);
\end{tikzpicture}
\end{questions}
\end{document}
"""
        parsed = parse_exam_source(src)
        task = [el for el in parsed['elements'] if el['kind'] == 'task'][0]
        self.assertEqual(task['text'].strip(), 'Решите уравнение.')
        self.assertEqual(task['choices'][0], '10;−10')
        self.assertEqual(len(task['choices']), 4)
        self.assertNotIn('tikzpicture', task['text'])
        self.assertNotIn('oneparcheckboxes', task['text'])
        self.assertEqual(task['subitems'], [])

    def test_preprocess_starredtask(self):
        src = r'\starredtask{2}{\columned{3}{Решите:}{\item $x=1$; \item $x=2$.}}'
        out = preprocess_mathneo(src)
        self.assertIn(r'\task{2}{3}{Решите:}', out)
        self.assertIn(r'\item $x=1$', out)

    def test_emit_roundtrip_shape(self):
        draft = {
            'title': 'Тест',
            'header': {'title': 'Тест', 'left': '7 класс', 'right': '',
                       'subtitle': ''},
            'elements': [
                {'kind': 'rubric', 'rubric': 'Устно', 'note': ''},
                {'kind': 'task', 'text': 'Найдите $x$.', 'subitems': ['а', 'б'],
                 'stars': 1, 'columns': 2, 'answer': '1', 'solution': '',
                 'skip': False},
            ],
        }
        tex = emit_egor_tex(draft)
        self.assertIn(r'\bighead{Тест}{7 класс}{}', tex)
        self.assertIn(r'\rubr{Устно}', tex)
        self.assertIn(r'\task{1}{2}', tex)


class SplitHelpersTests(unittest.TestCase):
    def test_split_top_items_nested(self):
        body = r'\item A \begin{enumerate}\item a\end{enumerate} \item B'
        items = split_top_items(body)
        self.assertEqual(len(items), 2)
        self.assertIn('A', items[0])
        self.assertIn(r'\begin{enumerate}', items[0])

    def test_alpha_split(self):
        stem, parts = split_alpha_subitems(r'Сократите: а)~$1$; б)~$2$.')
        self.assertIn('Сократите', stem)
        self.assertEqual(len(parts), 2)

    def test_alpha_split_latin_after_display(self):
        text = (
            'Дана функция $y=f(x)$, где\n'
            '$$\n'
            r'f(x)=\left\{\begin{array}{l}'
            r'-2 x+3, \text { если }-4 \leq x<1, \\'
            r'2 x-1, \text { если } 1 \leq x \leq 4'
            r'\end{array}\right. \text {. }'
            '\n$$\n'
            r'a) Найдите $f(-3), f(2), f(1)$;\\'
            r'б) Постройте график функции $y=f(x)$.'
        )
        stem, parts = split_alpha_subitems(text)
        self.assertIn('f(x)', stem)
        self.assertEqual(len(parts), 2)
        self.assertIn('f(-3)', parts[0])
        self.assertNotIn(r'\\', parts[0])
        self.assertIn('график', parts[1])

    def test_choice_envs_and_answer_grid(self):
        text = (
            'Решите уравнение.\n'
            r'\begin{oneparcheckboxes}'
            r'\choice 10;−10'
            r'\choice нет корней'
            r'\end{oneparcheckboxes}'
        )
        stem, choices = extract_choice_envs(text)
        self.assertEqual(stem, 'Решите уравнение.')
        self.assertEqual(choices, ['10;−10', 'нет корней'])
        grid = (
            r'Найдите $x$.'
            r'\vspace{2mm}\noindent'
            r'\begin{tikzpicture}[scale=0.5]'
            r'\draw [help lines] (0,0) grid (37,5);'
            r'\end{tikzpicture}'
        )
        self.assertEqual(strip_answer_grids(grid), r'Найдите $x$.')

    def test_strip_layout_vspace(self):
        text = 'Решите уравнение.\n\\vspace{10mm}\n\\medskip'
        self.assertEqual(strip_layout_space(text), 'Решите уравнение.')

    def test_strip_layout_setcounter_multicols_noindent(self):
        text = (
            r'Найдите корень уравнения: \begin{multicols}{2} \end{multicols}'
            r'\setcounter{enumi}{\value{count}}\noindent')
        self.assertEqual(strip_layout_space(text), 'Найдите корень уравнения:')
        commented = (
            r'Вычислите: %\begin{multicols}{2} %\end{multicols}')
        self.assertEqual(strip_layout_space(commented), 'Вычислите:')

    def test_strip_subitem_punct_and_quad(self):
        self.assertEqual(
            strip_subitem_punct(r'$1,4 y-0,5(5 y-3)=-0,6(y-2)$;'),
            r'$1,4 y-0,5(5 y-3)=-0,6(y-2)$')
        self.assertEqual(
            strip_subitem_punct(r'$\displaystyle \frac{12 a b}{4 a} $;\quad'),
            r'$\displaystyle \frac{12 a b}{4 a} $')
        self.assertEqual(
            strip_subitem_punct('Приведите пример.'),
            'Приведите пример.')
        self.assertEqual(
            strip_subitem_punct('чему равен $x$?'),
            'чему равен $x$?')

    def test_exam_tags_from_oge_and_fipi(self):
        self.assertEqual(
            exam_codes_from_elements([
                {'kind': 'task', 'text': r'\oge Решите уравнение.'},
            ], grade=9),
            ['OGE_2026'])
        self.assertEqual(
            exam_codes_from_elements([
                {'kind': 'task', 'text': r'\fipi Найдите корень уравнения.'},
            ], grade=11),
            ['EGE_PROFILE_2026'])
        self.assertEqual(
            exam_codes_from_elements([
                {'kind': 'rubric', 'rubric': r'\fipi Линейные уравнения'},
            ], grade=11),
            ['EGE_PROFILE_2026'])


class TitleOriginTests(unittest.TestCase):
    def test_filename_title_detected(self):
        rel = '9 класс/matvert9-teorver-geom_ver-duga.tex'
        self.assertTrue(title_looks_from_filename(
            'Teorver geom ver duga', rel))
        self.assertFalse(title_looks_from_filename(
            'Геометрическая вероятность. Дуга', rel))

    def test_make_draft_marks_filename_origin(self):
        draft = make_draft(
            rel_path='9 класс/matvert9-teorver-geom_ver-duga.tex',
            source_path='/tmp/x.tex',
            dialect='enumerate',
            grade=9,
            header={'title': '', 'left': '', 'right': '', 'subtitle': ''},
            elements=[])
        self.assertEqual(draft['title_origin'], 'filename')
        self.assertTrue(title_looks_from_filename(
            draft['title'], draft['rel_path']))

    def test_proposed_title_flag(self):
        draft = {
            'title': 'Teorver geom ver duga',
            'header': {'title': 'Teorver geom ver duga'},
            'warnings': [],
        }
        apply_proposed_title(draft, 'Геометрическая вероятность. Дуга')
        self.assertEqual(draft['title_origin'], 'proposed')
        self.assertEqual(draft['title'], 'Геометрическая вероятность. Дуга')
        self.assertEqual(draft['header']['title'], draft['title'])
        self.assertIn(TITLE_PROPOSED_WARNING, draft['warnings'])


class ClassifyAliasTests(unittest.TestCase):
    def test_geom_probability_and_prefixed_title(self):
        duga = {
            'title': 'Геометрическая вероятность. Дуга',
            'header': {'title': 'Геометрическая вероятность. Дуга'},
            'rel_path': '9 класс/matvert9-teorver-geom_ver-duga.tex',
            'elements': [],
        }
        codes = [c['code'] for c in suggest_topic(duga)]
        self.assertIn('STA.03.05', codes)
        kr = {
            'title': 'Контрольная работа №1. Начальные геометрические сведения',
            'header': {
                'title': 'Контрольная работа №1. Начальные геометрические сведения'},
            'rel_path': '7 класс/geom-kr1.tex',
            'elements': [],
        }
        kr_codes = [c['code'] for c in suggest_topic(kr)]
        self.assertTrue(
            any(c == 'GEO.01' or c.startswith('GEO.01.') for c in kr_codes))

    def test_short_final_title_does_not_inherit_probability(self):
        draft = {
            'title': 'Подготовка к итоговой работе',
            'header': {'title': 'Подготовка к итоговой работе'},
            'rel_path': '5 класс/math5-povt1.tex',
            'elements': [
                {'kind': 'task',
                 'text': 'Вычислите $7\\frac{1}{5}:2\\frac{4}{7}$.'},
            ],
        }
        codes = [c['code'] for c in suggest_topic(draft)]
        self.assertNotIn('STA.03', codes)
        self.assertFalse(any(c.startswith('STA') for c in codes))
        classify_draft(draft, overwrite=True, recheck=True)
        self.assertEqual(draft.get('topic_code') or '', '')
        self.assertTrue(draft.get('needs_topic_review'))

    def test_natural_numbers_alias_is_confident(self):
        draft = {
            'title': 'Действия с натуральными числами',
            'header': {'title': 'Действия с натуральными числами'},
            'rel_path': '6 класс/math6-sr1.tex',
            'elements': [],
        }
        cands = suggest_topic(draft)
        self.assertTrue(cands)
        self.assertEqual(cands[0]['code'], 'ARI.01.05')
        self.assertTrue(topic_is_confident(cands[0]))
        classify_draft(draft, overwrite=True)
        self.assertEqual(draft['topic_code'], 'ARI.01.05')

    def test_rubric_does_not_set_mixed_final(self):
        draft = {
            'title': 'Подготовка к итоговой работе',
            'header': {'title': 'Подготовка к итоговой работе'},
            'rel_path': '6 класс/promatvert/math6-final-basic.tex',
            'elements': [
                {'kind': 'rubric', 'rubric': 'Комбинаторика'},
                {'kind': 'task', 'text': 'Вычислите $2+3$.'},
            ],
        }
        classify_draft(draft, overwrite=True, recheck=True)
        self.assertEqual(draft.get('topic_code') or '', '')

    def test_task_content_below_barrier(self):
        self.assertFalse(topic_is_confident({
            'code': 'ALG.03', 'score': 0.88, 'reason': 'task-content',
        }))
        self.assertTrue(topic_is_confident({
            'code': 'STA.03.05', 'score': 1.0, 'reason': 'exact-name',
        }))


class SubitemSplitTests(unittest.TestCase):
    def test_semicolon_and_labels(self):
        self.assertEqual(split_pile(r'$4$; $9$', 2), [r'$4$', r'$9$'])
        self.assertEqual(
            split_pile(r'а) $4$; б) $9$', 2), [r'$4$', r'$9$'])
        self.assertEqual(
            split_pile(r'$-12{,}2;\ -9;\ \dfrac{7}{15};\ -1{,}25$', 4),
            [r'$-12{,}2$', r'$-9$', r'$\dfrac{7}{15}$', r'$-1{,}25$'])
        self.assertIsNone(split_pile(r'$1{,}5$; $2$', 3))

    def test_maybe_split_clears_pile(self):
        el = {
            'kind': 'task',
            'subitems': ['$10\\%$ от 50', '$20\\%$ от 80'],
            'answer': r'$5$; $16$',
            'solution': 'а) $10\\%$ от $50$ это $5$.\nб) $20\\%$ от $80$ это $16$.',
            'subitem_answers': [],
            'subitem_solutions': [],
        }
        self.assertTrue(maybe_split_element(el))
        self.assertEqual(el['subitem_answers'], [r'$5$', r'$16$'])
        self.assertEqual(len(el['subitem_solutions']), 2)
        self.assertEqual(el['answer'], '')
        self.assertEqual(el['solution'], '')


class PreserveSkipTests(unittest.TestCase):
    def test_failed_reparse_keeps_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / '9_ostatki.tex'
            tex.write_text('% empty\n', encoding='utf-8')
            with mock.patch(
                    'worksheet_corpus.paths.OUTPUT_DIR', root):
                save_draft({
                    'schema_version': 1,
                    'id': '6 класс/9_ostatki',
                    'rel_path': '6 класс/9_ostatki.tex',
                    'status': 'skipped',
                    'elements': [],
                    'warnings': ['Разбор не удался: нет парсера'],
                })
                again = store_failed_draft(
                    tex, rel_path='6 класс/9_ostatki.tex',
                    grade=6, dialect='other',
                    error=ValueError('Нет парсера для диалекта other'))
                self.assertEqual(again['status'], 'skipped')
                self.assertEqual(
                    load_draft('6 класс/9_ostatki')['status'], 'skipped')

    def test_parse_and_store_skips_skipped_draft(self):
        src = (
            r'\documentclass{article}\begin{document}'
            r'\begin{enumerate}\item $1+1$\end{enumerate}'
            r'\end{document}')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / 'ok.tex'
            tex.write_text(src, encoding='utf-8')
            with mock.patch(
                    'worksheet_corpus.paths.OUTPUT_DIR', root):
                save_draft({
                    'schema_version': 1,
                    'id': '6 класс/ok',
                    'rel_path': '6 класс/ok.tex',
                    'status': 'skipped',
                    'elements': [],
                })
                draft = parse_and_store(
                    tex, rel_path='6 класс/ok.tex', grade=6,
                    dialect='enumerate')
                self.assertEqual(draft['status'], 'skipped')
                self.assertEqual(draft['elements'], [])

    def test_preserve_element_skip(self):
        existing = {
            'status': 'needs_review',
            'elements': [
                {'kind': 'rubric', 'rubric': 'A'},
                {'kind': 'task', 'text': 'one', 'skip': True},
                {'kind': 'task', 'text': 'two', 'skip': False},
            ],
        }
        draft = {
            'status': 'needs_review',
            'elements': [
                {'kind': 'rubric', 'rubric': 'A'},
                {'kind': 'task', 'text': 'one', 'skip': False},
                {'kind': 'task', 'text': 'two', 'skip': False},
            ],
        }
        _preserve_review_fields(draft, existing)
        self.assertTrue(draft['elements'][1]['skip'])
        self.assertFalse(draft['elements'][2]['skip'])


class CorpusCleanupTests(unittest.TestCase):
    def test_drops_proof_answers(self):
        self.assertEqual(clean_answer_junk('доказано'), '')
        self.assertEqual(clean_answer_junk('Доказательство'), '')
        self.assertEqual(clean_answer_junk('см. решение'), '')
        self.assertEqual(clean_answer_junk('Верно'), 'Верно')
        self.assertEqual(clean_answer_junk('чётная (доказано)'), 'чётная')
        self.assertEqual(
            clean_answer_junk(r'а) доказано; б) $3-\sqrt{5}$'),
            r'б) $3-\sqrt{5}$')

    def test_equation_answers_get_variable(self):
        self.assertEqual(
            rewrite_equation_answer(r'Решите уравнение $x^2=4$.', r'$2; -2$'),
            r'$x=2; x=-2$')
        self.assertEqual(
            rewrite_equation_answer('Решите уравнение.', r'$\pm 3$'),
            r'$x=3; x=-3$')
        self.assertEqual(
            rewrite_equation_answer(
                r'Решите уравнение $\log_2 y=3$.', r'$8$'),
            r'$y=8$')
        self.assertEqual(
            rewrite_equation_answer(
                r'Решите уравнение $x^2=4$.', r'$x=2; -2$'),
            r'$x=2; x=-2$')
        self.assertEqual(
            rewrite_equation_answer(
                'Решите уравнение. Если корней несколько, запишите их через точку с запятой.',
                r'$22$'),
            r'$x=22$')
        self.assertEqual(
            rewrite_equation_answer(
                r'Решите уравнение $\sin x=0$. Найдите его решения на отрезке.',
                r'$\pi; 2\pi$'),
            r'$x=\pi; x=2\pi$')
        self.assertEqual(
            rewrite_equation_answer(
                'При каких $a$ уравнение имеет корни?', r'$1$'),
            r'$1$')
        self.assertEqual(
            rewrite_equation_answer('Решите уравнение.', 'нет корней'),
            'нет корней')

    def test_clean_draft_layout_and_answers(self):
        draft = {
            'id': 't',
            'elements': [{
                'kind': 'task',
                'text': r'Решите уравнение: \begin{multicols}{2}\end{multicols}',
                'subitems': [r'$2x=4$;\quad', r'$y-1=0$.'],
                'subitem_answers': [r'$2$', r'$1$'],
                'answer': 'доказано',
                'choices': [],
            }],
        }
        clean_draft(draft)
        el = draft['elements'][0]
        self.assertEqual(el['text'], 'Решите уравнение:')
        self.assertEqual(el['subitems'][0], r'$2x=4$')
        self.assertEqual(el['subitems'][1], r'$y-1=0$')
        self.assertEqual(el['subitem_answers'][0], r'$x=2$')
        self.assertEqual(el['subitem_answers'][1], r'$y=1$')
        self.assertEqual(el['answer'], '')


class ImagePathTests(unittest.TestCase):
    TINY_PNG = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
        b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')

    def test_resolve_uses_assets_dir_when_host_path_missing(self):
        from worksheet_corpus.parse import resolve_element_image_paths
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            key = '8 класс/matvert8-geom-prop_otr'
            name = 'fig.png'
            dest = out / 'assets' / key.replace('/', '__')
            dest.mkdir(parents=True)
            (dest / name).write_bytes(self.TINY_PNG)
            el = {
                'image_names': [name],
                'image_files': [f'/Users/other/missing/{name}'],
            }
            with mock.patch('worksheet_corpus.paths.OUTPUT_DIR', out):
                found, missing = resolve_element_image_paths(key, el)
            self.assertEqual(missing, [])
            self.assertEqual([p.name for p in found], [name])
            self.assertTrue(found[0].is_file())


if __name__ == '__main__':
    unittest.main()
