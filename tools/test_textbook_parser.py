import tempfile
import unittest
from pathlib import Path

from tools.textbook_parser import (
    Marker,
    ImportBundle,
    bundle_from_text,
    collapse_repeated_lead,
    expected_shestakov_ids,
    extract_images,
    normalize_imported_text,
    numeric_markers,
    path_at,
    parse_galitsky,
    parse_shestakov,
    parse_ziv,
    redistribute_glued_subitem_answers,
    split_compact_author_material,
    ZIV_UNEVEN_VARIANT_WARNING,
    rewalk_ziv_merged_body,
    split_leaked_structural_tail,
    sections,
    shestakov_source_path,
    shestakov_markers,
    split_answer_solution,
    split_subitems,
    strip_leading_subitem_label,
    task_from_block,
    write_bundle,
)
from problems.textbook_parser import _ziv_looks_like_topic_title  # noqa: E402


class TextbookParserTests(unittest.TestCase):
    def test_explicit_answer_stops_before_solution_after_cleanup(self):
        answer, solution = split_answer_solution(
            "Ответ: 2.\n\nРешение: сложим слагаемые.")
        self.assertEqual(answer, "2.")
        self.assertEqual(solution, "Решение: сложим слагаемые.")

    def test_noun_resheniya_is_not_a_solution_heading(self):
        answer, solution = split_answer_solution(
            r"если \(a<-2\), то 2 решения.")
        self.assertIn("2 решения", answer)
        self.assertEqual(solution, "")

    def test_ocr_spaced_solution_heading_is_split(self):
        answer, solution = split_answer_solution(
            r"1. Решени е: \(x=1\).")
        self.assertIn("1", answer)
        self.assertIn("ешени", solution)
        spaced, spaced_sol = split_answer_solution(
            r"$b_1=2$. P е шени е: $b_1+b_1 q=14$.")
        self.assertIn("b_1", spaced)
        self.assertNotIn("шени", spaced)
        self.assertIn("шени", spaced_sol)

    def test_shestakov_expected_number_grid_has_1220_tasks(self):
        expected = expected_shestakov_ids()
        self.assertEqual(len(expected), 1220)
        self.assertIn("1.1.A01", expected)
        self.assertIn("10.3.D15", expected)
        self.assertIn("11.1.D10", expected)

    def test_shestakov_source_path_has_chapter_and_paragraph(self):
        self.assertEqual(shestakov_source_path("4.2.B03"), [
            "Глава 4. Неравенства",
            "§2. Дробно-рациональные неравенства",
        ])
        self.assertEqual(shestakov_source_path("10.3.D15"), [
            "Приложение 1. Задачи по геометрии",
            "§3. Окружности",
        ])

    def test_section_path_replaces_sibling_at_same_level(self):
        text = (
            r"\section{Глава 1}\subsection{Тема A} задача "
            r"\subsection{Тема B} другая задача"
        )
        headings = sections(text)
        pos = text.index("другая задача")
        self.assertEqual(path_at(headings, pos), ["Глава 1", "Тема B"])

    def test_shestakov_normalizes_split_and_cyrillic_code(self):
        text = "\n".join([
            r"1.1.A01 one",
            r"  \item[1.1.] В02 two",
            r"2.3.С10 three",
            r"В тексте упомянута задача 9.9.D09, но это не маркер.",
            r"\caption{3.4.C05}",
        ])
        self.assertEqual(
            [item.external_id for item in shestakov_markers(text)],
            ["1.1.A01", "1.1.B02", "2.3.C10", "3.4.C05"],
        )

    def test_caption_marker_keeps_task_image(self):
        task_text = "\n".join([
            r"\begin{figure}",
            r"\includegraphics{graph-79}",
            r"\caption{7.1.D10}",
            r"\end{figure}",
            "Условие с графиком.",
        ])
        tasks, _ = parse_shestakov(task_text, "")
        self.assertEqual([task.external_id for task in tasks], ["7.1.D10"])
        self.assertEqual(tasks[0].images, ["graph-79"])
        self.assertIn("Условие с графиком", tasks[0].text_latex)
        self.assertNotIn(r"\begin{figure}", tasks[0].text_latex)
        self.assertIn(r"\taskpic{1}", tasks[0].text_latex)

    def test_solution_marker_can_end_previous_line(self):
        task_text = "\n".join([
            "1.1.A01 Первое условие.",
            "1.1.A02 Второе условие.",
        ])
        solution_text = "\n".join([
            "1.1.A01 Ответ: 1. 1.1.A02",
            "Ответ: 2.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(
            [task.author_answer_latex for task in tasks], ["1", "2"])
        self.assertEqual(diagnostics["matched_solutions"], 2)

    def test_immediate_next_code_caption_stays_with_current_solution(self):
        task_text = "\n".join([
            "10.2.A09 Первая задача.",
            "10.2.A10 Вторая задача.",
        ])
        solution_text = "\n".join([
            "10.2.A09",
            r"\begin{figure}",
            r"\includegraphics{diagram-a09}",
            r"\caption{10.2.A10}",
            r"\end{figure}",
            "Решение первой задачи.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        by_id = {task.external_id: task for task in tasks}
        self.assertIn(
            r"\taskpic{1}", by_id["10.2.A09"].author_solution_latex)
        self.assertEqual(by_id["10.2.A09"].images, ["diagram-a09"])
        self.assertEqual(by_id["10.2.A10"].author_solution_latex, "")
        self.assertEqual(diagnostics["matched_solutions"], 1)

    def test_caption_after_substantive_solution_can_start_next_solution(self):
        task_text = "\n".join([
            "7.2.C04 Первая задача.",
            "7.2.C05 Вторая задача.",
        ])
        solution_text = "\n".join([
            "7.2.C04 Решение первой задачи.",
            r"\begin{figure}",
            r"\includegraphics{diagram-c05}",
            r"\caption{7.2.C05}",
            r"\end{figure}",
            "Решение второй задачи.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        by_id = {task.external_id: task for task in tasks}
        self.assertNotIn(
            "diagram-c05", by_id["7.2.C04"].author_solution_latex)
        self.assertIn(
            r"\taskpic{1}", by_id["7.2.C05"].author_solution_latex)
        self.assertEqual(by_id["7.2.C05"].images, ["diagram-c05"])
        self.assertEqual(diagnostics["matched_solutions"], 2)

    def test_shestakov_sorts_physical_columns_by_canonical_code(self):
        task_text = "\n".join([
            r"\section*{§1. Тема}",
            r"1.1.A01 Первая.",
            r"\begin{itemize}",
            r"  \item[1.1.] C01 Третья.",
            r"  \item[1.1.] B01 Вторая.",
            r"\end{itemize}",
        ])
        solution_text = "\n".join([
            "1.1.A01 Ответ: 1.",
            "1.1.B01 Ответ: 2.",
            "1.1.C01 Ответ: 3.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["1.1.A01", "1.1.B01", "1.1.C01"],
        )
        self.assertEqual(
            diagnostics["physical_order_break_ids"], ["1.1.B01"])
        self.assertNotIn(
            "Несбалансированные LaTeX-окружения внутри блока",
            tasks[0].warnings,
        )

    def test_duplicate_marker_still_limits_previous_block(self):
        task_text = "\n".join([
            "1.1.A01 Первое условие.",
            "1.1.A01 Дубль OCR.",
            "1.1.A02 Второе условие.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, "")
        self.assertEqual(diagnostics["duplicate_task_ids"], ["1.1.A01"])
        self.assertIn("Первое условие.", tasks[0].text_latex)
        self.assertIn("Дубль OCR.", tasks[0].text_latex)
        self.assertTrue(any(
            "Повторный маркер условия" in warning
            for warning in tasks[0].warnings))
        self.assertLess(tasks[0].confidence, 1)

    def test_duplicate_direct_solution_marker_is_still_a_boundary(self):
        task_text = "\n".join([
            "1.1.A01 Первая задача.",
            "1.1.A02 Вторая задача.",
        ])
        solution_text = "\n".join([
            "1.1.A01 Первое решение.",
            "1.1.A01 Дубль OCR решения.",
            "1.1.A02 Второе решение.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(
            tasks[0].author_solution_latex, "Первое решение.")
        self.assertNotIn("Дубль OCR", tasks[0].author_solution_latex)
        self.assertEqual(diagnostics["duplicate_solution_ids"], ["1.1.A01"])
        self.assertTrue(any(
            "Повторный маркер авторского ответа/решения" in warning
            for warning in tasks[0].warnings))
        self.assertLess(tasks[0].confidence, 1)

    def test_outer_list_does_not_trigger_environment_warning(self):
        task = task_from_block(
            Marker(0, 0, "1.1.A01"),
            r"Условие. \begin{itemize} \item[] Текст.",
            ["Тема"],
        )
        self.assertNotIn(
            "Несбалансированные LaTeX-окружения внутри блока",
            task.warnings,
        )

    def test_mixed_plain_and_item_subitems_are_split(self):
        task_text = "\n".join([
            "1.1.A01 Найдите:",
            r"\\ а) $1+1$;",
            r"\item[б)] $2+2$.",
        ])
        tasks, _ = parse_shestakov(task_text, "")
        self.assertEqual(tasks[0].text_latex, "Найдите:")
        self.assertEqual(
            [(item.label, item.text_latex) for item in tasks[0].subitems],
            [("а", "$1+1$"), ("б", "$2+2$")],
        )

    def test_tilde_and_same_line_subitem_markers_are_split(self):
        tilde_text = "\n".join([
            r"4.3.D10 Найдите все пары \((x ; y)\) целых чисел \(x\) и \(y\), для которых:",
            r"а)~\(5 \sqrt{3 x-2 y-4}+3 \sqrt{2 x+3 y-7} \leqslant 2\);",
            r"б)~\(4 \sqrt{3 x-2 y+1}+7 \sqrt{2 x-3 y+4} \leqslant 3\).",
            r"§1. Системы целых алгебраических уравнений Уровень А",
        ])
        inline_text = (
            "1.1.D04 a) Найдите наименьшее натуральное число, большее 2. "
            "б) Найдите наименьшее натуральное число, большее 6."
        )

        tilde_tasks, _ = parse_shestakov(tilde_text, "")
        inline_tasks, _ = parse_shestakov(inline_text, "")

        self.assertEqual(
            tilde_tasks[0].text_latex,
            r"Найдите все пары \((x ; y)\) целых чисел \(x\) и \(y\), для которых:")
        self.assertEqual(
            [item.label for item in tilde_tasks[0].subitems], ['а', 'б'])
        self.assertTrue(all(
            not item.text_latex.startswith(('а)', 'б)', 'а)~', 'б)~'))
            for item in tilde_tasks[0].subitems))
        self.assertNotIn("§1", tilde_tasks[0].subitems[-1].text_latex)
        self.assertNotIn("Уровень", tilde_tasks[0].subitems[-1].text_latex)
        self.assertEqual(len(inline_tasks[0].subitems), 2)
        self.assertIn("большее 2", inline_tasks[0].subitems[0].text_latex)
        self.assertIn("большее 6", inline_tasks[0].subitems[1].text_latex)

    def test_imported_text_drops_trailing_space_before_punctuation(self):
        self.assertEqual(
            normalize_imported_text(
                r'Между какими числами заключено \(\sqrt{170}\) ?\\'),
            r'Между какими числами заключено \(\sqrt{170}\)?')
        self.assertEqual(
            strip_leading_subitem_label(r'а) $564\cdot645$', 'а'),
            r'$564\cdot645$')
        self.assertEqual(
            strip_leading_subitem_label(r'б) второй пункт', 'а'),
            r'б) второй пункт')
        self.assertEqual(
            collapse_repeated_lead(
                'Найдите значение выражения: Найдите значение выражения:'),
            'Найдите значение выражения:')

    def test_imported_text_heals_ocr_linebreak_and_emdash(self):
        from problems.textbook_parser import apply_imported_math

        self.assertEqual(
            normalize_imported_text(
                r'Последовательность задана формулой \(c_{n}=2 n^{2}-5 n+\) +1.'),
            r'Последовательность задана формулой \(c_{n}=2 n^{2}-5 n+1\).')
        self.assertEqual(
            normalize_imported_text(
                r'формулой \(c_{n}=-3 n^{2}+\) \(+7 n+4\).'),
            r'формулой \(c_{n}=-3 n^{2}+7 n+4\).')
        self.assertEqual(
            normalize_imported_text(
                r'\(a_{2} a_{4}=\) \(=160\). Найдите \(S_{6}\)'),
            r'\(a_{2} a_{4}=160\). Найдите \(S_{6}\)')
        self.assertEqual(
            normalize_imported_text(
                r'графика функции \(y=x^{2}\) - \(-7 x-9\)'),
            r'графика функции \(y=x^{2}-7 x-9\)')
        self.assertEqual(
            normalize_imported_text(
                r'при \(x \in\) \(\in(-\infty ;-3]\)'),
            r'при \(x \in(-\infty ;-3]\)')
        self.assertEqual(
            normalize_imported_text(
                r'у которой \(b_{1}\) - \(b_{4}=0,6\)'),
            r'у которой \(b_{1} - b_{4}=0,6\)')
        self.assertEqual(
            normalize_imported_text(
                r'\(a_{n}\) - арифметическая прогрессия. \(a\) и \(b\) - рациональные числа.'),
            r'\(a_{n}\) — арифметическая прогрессия. \(a\) и \(b\) — рациональные числа.')
        self.assertEqual(
            normalize_imported_text(r'\(x - y\) и слово - слово'),
            r'\(x - y\) и слово — слово')
        self.assertEqual(
            apply_imported_math(r'D = (-5a)^2 - 4 \cdot 1 \cdot 4'),
            r'$D = (-5a)^2 - 4 \cdot 1 \cdot 4$')
        self.assertEqual(
            apply_imported_math(r'$\frac{2}{3}<\frac{4}{5}$'),
            r'$\displaystyle \frac{2}{3}<\frac{4}{5}$')
        self.assertEqual(
            apply_imported_math(r'\(\frac{1}{2}\)'),
            r'\(\displaystyle \frac{1}{2}\)')
        self.assertEqual(
            apply_imported_math(r'\[\frac{1}{2}\]'),
            r'\[\frac{1}{2}\]')
        self.assertEqual(
            apply_imported_math(r'$\displaystyle \frac{1}{2}$'),
            r'$\displaystyle \frac{1}{2}$')
        from problems.textbook_parser import (
            apply_imported_answer, clean_heading, strip_heading_dot,
            strip_imported_answer_punct)
        self.assertEqual(
            strip_heading_dot('Чётные и нечётные функции.'),
            'Чётные и нечётные функции')
        self.assertEqual(
            clean_heading('10. Чётные и нечётные функции.'),
            '10. Чётные и нечётные функции')
        self.assertEqual(
            apply_imported_answer(r'$\frac{2}{3}<\frac{4}{5}$.'),
            r'$\displaystyle \frac{2}{3}<\frac{4}{5}$')
        self.assertEqual(apply_imported_answer('2.'), '2')
        self.assertEqual(
            apply_imported_answer('Нет корней.'), 'Нет корней.')
        self.assertEqual(apply_imported_answer(r'\{-2;1\}'), r'$\{-2;1\}$')
        self.assertEqual(
            apply_imported_answer(r'\(\{-2 \pm \sqrt{2}\}\)'),
            r'$\{-2 \pm \sqrt{2}\}$')
        self.assertEqual(
            apply_imported_answer(r'$\(\{-2 \pm \sqrt{2}\}$\)'),
            r'$\{-2 \pm \sqrt{2}\}$')
        self.assertEqual(
            apply_imported_answer(r'\((2 ; 3) ;(3 ; 2)'),
            r'$(2 ; 3) ;(3 ; 2)$')
        self.assertEqual(
            apply_imported_answer(
                r'$\left(-1 ; \displaystyle \frac{9}{4}\right) ;(4 ;-9)\)$'),
            r'$\left(-1 ; \displaystyle \frac{9}{4}\right) ;(4 ;-9)$')
        self.assertEqual(
            apply_imported_answer(
                r'(-1,75 ;-3) ;$\displaystyle \left(-\frac{7}{6}$ '
                r';$-2\right)$'),
            r'$(-1,75 ;-3) ;\displaystyle \left(-\frac{7}{6} ;-2\right)$')
        self.assertEqual(
            apply_imported_answer(
                r'$\displaystyle \left\{\frac{5}{4}$ ; $3\right\}$)$'),
            r'$\displaystyle \left\{\frac{5}{4} ; 3\right\}$')
        self.assertEqual(
            strip_imported_answer_punct('см. рис.'), 'см. рис')

    def test_subitem_body_does_not_keep_its_own_marker(self):
        task_text = "\n".join([
            r"1.3.A02 Найдите значение выражения:",
            r"\\ а) а) $564\cdot645-563\cdot645$",
            r"\\ б) $1+1$",
        ])

        tasks, _ = parse_shestakov(task_text, "")

        self.assertEqual(tasks[0].text_latex, "Найдите значение выражения:")
        self.assertEqual(
            [item.text_latex for item in tasks[0].subitems],
            [r"$564\cdot645-563\cdot645$", r"$1+1$"],
        )

    def test_subitem_punctuation_matches_tex_import_rules(self):
        task_text = "\n".join([
            "1.1.A01 Выполните:",
            r"\\ а) Докажите неравенство.",
            r"\\ б) Верно ли обратное?",
            r"\\ в) найдите значение;",
            r"\\ г) $2+2$.",
            r"\\ д) $3+3$,",
        ])

        tasks, _ = parse_shestakov(task_text, "")

        self.assertEqual(
            [item.text_latex for item in tasks[0].subitems],
            [
                "Докажите неравенство.",
                "Верно ли обратное?",
                "найдите значение",
                "$2+2$",
                "$3+3$",
            ],
        )

    def test_solution_subitems_use_the_same_punctuation_rules(self):
        task_text = "\n".join([
            "1.1.A01 Выполните:",
            r"\\ а) первый пункт;",
            r"\\ б) второй пункт.",
        ])
        solution_text = "\n".join([
            r"\subsection*{1.1.A01}",
            r"\\ а) Получаем результат.",
            r"\\ б) подставляем значение;",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        self.assertEqual(
            [item.author_solution_latex for item in tasks[0].subitems],
            ["Получаем результат.", "подставляем значение"],
        )

    def test_nested_numbered_list_stays_inside_letter_subitem(self):
        task_text = "\n".join([
            "1.1.A01 Исследуйте:",
            r"\\ а) первый график",
            r"\begin{itemize}",
            r"\item[1)] нуль;",
            r"\item[2)] минимум.",
            r"\end{itemize}",
            r"\\ б) второй график.",
        ])
        tasks, _ = parse_shestakov(task_text, "")
        self.assertEqual(
            [item.label for item in tasks[0].subitems], ["а", "б"])
        self.assertIn("нуль", tasks[0].subitems[0].text_latex)
        self.assertIn("минимум", tasks[0].subitems[0].text_latex)
        self.assertNotIn(r"\item", tasks[0].subitems[0].text_latex)
        self.assertIn("1)~нуль", tasks[0].subitems[0].text_latex)

    def test_misnested_second_letter_is_promoted_over_numbered_items(self):
        task_text = "\n".join([
            "7.1.A01 a) Первый график:",
            r"\begin{itemize}",
            r"\item[1)] нули;",
            r"\item[2)] минимум.",
            r"\item[б)] Второй график:",
            r"\begin{itemize}",
            r"\item[1)] нули;",
            r"\end{itemize}",
            r"\item[2)] максимум.",
            r"\end{itemize}",
        ])
        tasks, _ = parse_shestakov(task_text, "")
        self.assertEqual(
            [item.label for item in tasks[0].subitems], ["a", "б"])
        self.assertTrue(all(
            r"\item" not in item.text_latex for item in tasks[0].subitems))
        self.assertIn("1)~нули", tasks[0].subitems[0].text_latex)
        self.assertIn("2)~максимум", tasks[0].subitems[1].text_latex)

    def test_interleaved_column_tail_returns_to_previous_task(self):
        task_text = "\n".join([
            r"1.1.C01 а) Левая колонка, пункт а.",
            r"\begin{itemize}",
            r"\item[1.1.] B01 Правая колонка:",
            r"\\ а) Правый пункт а;",
            r"\\ б) Правый пункт б.",
            r"\begin{itemize}",
            r"\item[б)] Левая колонка, пункт б.",
            r"\end{itemize}",
            r"\end{itemize}",
        ])
        tasks, diagnostics = parse_shestakov(task_text, "")
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(
            [item.label for item in by_id["1.1.C01"].subitems], ["а", "б"])
        self.assertIn(
            "Левая колонка, пункт б",
            by_id["1.1.C01"].subitems[1].text_latex)
        self.assertEqual(
            [item.label for item in by_id["1.1.B01"].subitems], ["а", "б"])
        self.assertNotIn(
            "Левая колонка", by_id["1.1.B01"].subitems[1].text_latex)
        self.assertEqual(diagnostics["detached_column_fragments"], [{
            "from": "1.1.B01", "to": "1.1.C01",
        }])

    def test_numeric_markers_only_accept_task_boundaries(self):
        text = "1.1. First\n\\item[1.2.] Second\nvalue 3.14. not a task"
        self.assertEqual(
            [item.external_id for item in numeric_markers(text)], ["1.1", "1.2"]
        )

    def test_galitsky_pairs_author_answer_and_solution(self):
        source = r"""
\section*{§ 1. ДРОБИ}
\section*{Упражнения}
\item[1.1.] Вычислите $1+1$.
\item[1.2.] Докажите тождество.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. 2. 1.2. Верно. Решение. Раскроем скобки.
"""
        tasks, diagnostics = parse_galitsky(source)
        self.assertEqual([task.external_id for task in tasks], ["1.1", "1.2"])
        self.assertEqual(tasks[0].author_answer_latex, "2")
        self.assertIn("Решение", tasks[1].author_solution_latex)
        self.assertEqual(diagnostics["matched_solutions"], 2)

    def test_galitsky_distributes_partial_answers_by_subitem_label(self):
        source = r"""
\section*{§ 1. ДРОБИ}
\item[1.1.] Вычислите:
\begin{itemize}
  \item[а)] $1+1$;
  \item[б)] $2+2$;
  \item[в)] $3+3$.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. б) 4; в) 6.
"""
        tasks, diagnostics = parse_galitsky(source)

        self.assertEqual(diagnostics["matched_solutions"], 1)
        self.assertEqual(tasks[0].author_answer_latex, "")
        self.assertEqual(
            [item.author_answer_latex for item in tasks[0].subitems],
            ["", "4", "6"],
        )
        self.assertFalse(any(
            "не удалось распределить" in warning
            for warning in tasks[0].warnings))

    def test_galitsky_spaced_ocr_markers_bound_neighboring_answers(self):
        source = r"""
\section*{§ 2. ВЫРАЖЕНИЯ}
\item[2.21.] Найдите минимум.
\item[2.22.] Найдите максимум.
\item[2.23.] Найдите значение.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
2.21. -1.2 .22 .4 .2 .23 .1.
"""
        tasks, diagnostics = parse_galitsky(source)

        self.assertEqual(diagnostics["matched_solutions"], 3)
        self.assertEqual(
            [task.author_answer_latex for task in tasks], ["-1", "4", "1"])
        self.assertTrue(all(
            "Не найден авторский ответ/решение" not in task.warnings
            for task in tasks))

    def test_hint_is_kept_inside_solution(self):
        source = r"""
\section*{§ 1. ДРОБИ}
\item[1.1.] Докажите тождество.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. Верно. Указание. Раскройте скобки. Решение. После сокращения получаем ноль.
"""
        tasks, _ = parse_galitsky(source)
        self.assertEqual(tasks[0].author_answer_latex, "Верно.")
        self.assertIn("Указание", tasks[0].author_solution_latex)
        self.assertIn("Решение", tasks[0].author_solution_latex)

    def test_parsed_tasks_always_have_zero_stars(self):
        task_text = "\n".join([
            r"\section*{§1. Целые числа}",
            r"1.1.A01 Найдите $1+1$.",
        ])
        solution_text = r"1.1.A01 Ответ: 2."
        tasks, _ = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].stars, 0)

    def test_shestakov_pairs_separate_solution_book(self):
        task_text = "\n".join([
            r"\section*{§1. Целые числа}",
            r"1.1.A01 Найдите $1+1$.",
        ])
        solution_text = r"1.1.A01 $1+1=2$. Ответ: 2."
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].author_answer_latex, "2")
        self.assertIn("$1+1=2$", tasks[0].author_solution_latex)
        self.assertIn("Ответ: 2.", tasks[0].author_solution_latex)
        self.assertEqual(diagnostics["matched_solutions"], 1)

    def test_bundle_from_text_supports_web_upload_without_temp_files(self):
        bundle = bundle_from_text(
            "shestakov",
            "1.1.A01 Найдите $1+1$.",
            "1.1.A01 Ответ: 2.",
            tasks_file="book.tex",
            solutions_file="solutions.tex",
        )

        self.assertEqual(len(bundle.tasks), 1)
        self.assertEqual(bundle.tasks[0].author_answer_latex, "2")
        self.assertEqual(bundle.source, {
            "tasks_file": "book.tex",
            "solutions_file": "solutions.tex",
            "answers_file": "",
        })

    def test_solution_subitems_are_matched_without_top_level_labels(self):
        task_text = "\n".join([
            "1.1.A01 Вычислите:",
            r"\item[а)] $1+1$;",
            r"\item[б)] $2+2$.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\begin{itemize}",
            r"\item[a)] $1+1=2$. Ответ: 2.",
            r"\item[6)] $2+2=4$. Ответ: 4.",
            r"\end{itemize}",
        ])

        tasks, diagnostics = parse_shestakov(task_text, solution_text)

        task = tasks[0]
        self.assertEqual(task.author_solution_latex, "")
        self.assertEqual(
            [item.author_answer_latex for item in task.subitems],
            ["2", "4"],
        )
        self.assertEqual(
            [item.author_solution_latex for item in task.subitems],
            ["$1+1=2$. Ответ: 2", "$2+2=4$. Ответ: 4"],
        )
        for item in task.subitems:
            self.assertNotRegex(
                item.author_solution_latex, r"^(?:a|а|б|6)\)~?")
            self.assertNotIn(r"\item", item.author_solution_latex)

    def test_subitem_pair_survives_early_list_end(self):
        task_text = "\n".join([
            "1.1.A01 Сравните:",
            r"\begin{itemize}",
            r"\item[а)] первое выражение;",
            r"\end{itemize}",
            r"б) второе выражение.",
        ])
        solution_text = (
            r"1.1.A01 \item[a)] Первое решение; б) Второе решение.")

        tasks, _ = parse_shestakov(task_text, solution_text)

        task = tasks[0]
        self.assertEqual(
            [item.text_latex for item in task.subitems],
            ["первое выражение", "второе выражение"],
        )
        self.assertEqual(
            [item.author_solution_latex for item in task.subitems],
            ["Первое решение", "Второе решение."],
        )

    def test_inline_solution_subitems_are_split_after_semicolon(self):
        task_text = "\n".join([
            "1.1.A01 Вычислите:",
            r"\item[а)] $1+1$;",
            r"\item[б)] $2+2$.",
        ])
        solution_text = (
            r"1.1.A01 \item[a)] $1+1=2$; б) $2+2=4$.")

        tasks, _ = parse_shestakov(task_text, solution_text)

        task = tasks[0]
        self.assertEqual(task.author_answer_latex, "")
        self.assertEqual(task.author_solution_latex, "")
        self.assertEqual(
            [item.author_solution_latex for item in task.subitems],
            ["$1+1=2$", "$2+2=4$"],
        )

    def test_inline_subitems_split_after_closed_math(self):
        parent, items = split_subitems(
            r"\(\sin\alpha=-\frac{4}{5};\operatorname{tg}\alpha=-\frac{4}{3}\); "
            r"\(\operatorname{ctg}\alpha=-\frac{3}{4};\) б) "
            r"\(\cos\alpha=-\frac{4}{5};\sin\alpha=\frac{3}{5}\)",
            normalize_punctuation=False, minimum_items=1)
        self.assertIn(r"\sin\alpha", parent)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label.lower(), "б")
        self.assertIn(r"\cos\alpha", items[0].text_latex)
        self.assertNotIn("б)", parent)

    def test_compact_author_material_splits_after_math_close(self):
        answer, solution, items, _flat = split_compact_author_material(
            r"\(\displaystyle \sin \alpha=-\frac{4}{5} ; "
            r"\operatorname{tg} \alpha=-\frac{4}{3}\); "
            r"\(\displaystyle \operatorname{ctg} \alpha=-\frac{3}{4} ;\) б) "
            r"\(\displaystyle \cos \alpha=-\frac{4}{5} ; "
            r"\sin \alpha=\frac{3}{5} ; \operatorname{ctg} \alpha=-\frac{4}{3}\)")
        self.assertIn(r"\sin \alpha", answer)
        self.assertNotIn("б)", answer)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label.lower(), "б")
        self.assertIn(r"\cos \alpha", items[0].author_answer_latex)
        self.assertEqual(solution, "")

    def test_redistribute_glued_subitem_answers_repairs_stored_draft(self):
        from problems.textbook_parser import SubitemDraft
        task = type("Draft", (), {
            "author_answer_latex": "",
            "author_solution_latex": "",
            "subitems": [
                SubitemDraft(
                    "a",
                    r"\(\cos\alpha=\frac{3}{5}\)",
                    author_answer_latex=(
                        r"\(\sin\alpha=-\frac{4}{5};\operatorname{tg}\alpha="
                        r"-\frac{4}{3}\); \(\operatorname{ctg}\alpha="
                        r"-\frac{3}{4};\) б) \(\cos\alpha=-\frac{4}{5}\;"
                        r"\sin\alpha=\frac{3}{5}\)"),
                ),
                SubitemDraft("б", r"\(\operatorname{tg}\alpha=-\frac{3}{4}\)"),
            ],
        })()
        self.assertTrue(redistribute_glued_subitem_answers(task))
        self.assertIn(r"\sin\alpha", task.subitems[0].author_answer_latex)
        self.assertNotIn("б)", task.subitems[0].author_answer_latex)
        self.assertIn(r"\cos\alpha", task.subitems[1].author_answer_latex)
        self.assertEqual(task.author_answer_latex, "")

    def test_ziv_ocr_boldsymbol_six_goes_to_item_b(self):
        source = r"""
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 3
\begin{itemize}
  \item[2.] Найдите области определения функций:
  \item[а)] \(f(x)=\sqrt{x}\)
  \item[б)] \(f(x)=\sqrt{x+1}\)
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 3
\begin{itemize}
  \item[2.] a) \((-\infty ;-2,5) \cup(-2,5 ; 1) \cup(1 ;+\infty) ; \boldsymbol{6})(-\infty ;-1) \cup(-1 ; 1] \cup[4 ;+\infty)\).
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "kr/03/v3/2")
        by_label = {item.label: item.author_answer_latex for item in task.subitems}
        self.assertIn(r"-2,5", by_label["а"] if "а" in by_label else by_label["a"])
        self.assertTrue(
            by_label.get("б") or by_label.get("b") or by_label.get("6"))
        second = by_label.get("б") or by_label.get("b") or by_label.get("6")
        self.assertIn(r"-1", second)
        first = by_label.get("а") or by_label.get("a")
        self.assertNotIn("6)", first)

    def test_redistribute_ocr_boldsymbol_six_is_item_b(self):
        from problems.textbook_parser import SubitemDraft
        task = type("Draft", (), {
            "author_answer_latex": "",
            "author_solution_latex": "",
            "subitems": [
                SubitemDraft(
                    "a",
                    r"\(f(x)=\sqrt{x}\)",
                    author_answer_latex=(
                        r"$(-\infty ;-2,5) \cup(-2,5 ; 1) \cup(1 ;+\infty) ; "
                        r"\boldsymbol{6})(-\infty ;-1) \cup(-1 ; 1] \cup[4 ;+\infty)$"),
                ),
                SubitemDraft("б", r"\(f(x)=\sqrt{x+1}\)"),
            ],
        })()
        self.assertTrue(redistribute_glued_subitem_answers(task))
        first = task.subitems[0].author_answer_latex
        second = task.subitems[1].author_answer_latex
        self.assertIn(r"-2,5", first)
        self.assertNotIn("6)", first)
        self.assertNotIn("б)", first)
        self.assertIn(r"-1", second)
        self.assertIn(r"4", second)

    def test_redistribute_does_not_split_interval_ending_with_six(self):
        from problems.textbook_parser import SubitemDraft
        answer = r"$x\in(0 ; 6)$"
        task = type("Draft", (), {
            "author_answer_latex": "",
            "author_solution_latex": "",
            "subitems": [
                SubitemDraft("а", "первый", author_answer_latex=answer),
                SubitemDraft("б", "второй"),
            ],
        })()
        self.assertFalse(redistribute_glued_subitem_answers(task))
        self.assertEqual(task.subitems[0].author_answer_latex, answer)
        self.assertEqual(task.subitems[1].author_answer_latex, "")

    def test_solution_images_are_numbered_in_task_and_subitem_answers(self):
        task_text = "\n".join([
            "1.1.A01 Выберите рисунок:",
            r"\item[а)] первый;",
            r"\item[б)] второй.",
            "1.1.A02 Выберите общий рисунок.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\item[а)] Ответ: \includegraphics{answer-a.png}",
            r"\item[б)] Ответ: \includegraphics{answer-b.png}",
            "1.1.A02",
            r"Ответ: \includegraphics{answer-all.png}",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        first, second = tasks
        self.assertEqual(first.images, ["answer-a.png", "answer-b.png"])
        self.assertEqual(
            [item.author_answer_latex for item in first.subitems],
            [r"\taskpic{1}", r"\taskpic{2}"],
        )
        self.assertEqual(second.images, ["answer-all.png"])
        self.assertEqual(second.author_answer_latex, r"\taskpic{1}")
        combined_answers = "\n".join(
            [first.author_answer_latex, second.author_answer_latex]
            + [item.author_answer_latex for item in first.subitems]
        )
        self.assertNotIn("answer-a.png", combined_answers)
        self.assertNotIn("answer-b.png", combined_answers)
        self.assertNotIn("answer-all.png", combined_answers)

    def test_solution_image_numbers_are_replaced_in_one_pass(self):
        task_text = "\n".join([
            "1.1.A01 Выберите рисунок:",
            r"\item[а)] первый;",
            r"\item[б)] второй.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\item[а)] Ответ: \includegraphics{2}",
            r"\item[б)] Ответ: \includegraphics{1}",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        self.assertEqual(tasks[0].images, ["2", "1"])
        self.assertEqual(
            [item.author_answer_latex for item in tasks[0].subitems],
            [r"\taskpic{1}", r"\taskpic{2}"],
        )

    def test_nested_solution_numbering_stays_inside_subitem(self):
        task_text = "\n".join([
            "1.1.A01 Исследуйте:",
            r"\item[а)] первый график;",
            r"\item[б)] второй график.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\item[а)] Для первого:",
            r"\begin{itemize}",
            r"\item[1)] найдём нули;",
            r"\item[2)] найдём минимум.",
            r"\end{itemize}",
            r"\item[б)] Для второго графика решение отдельно.",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        first = tasks[0].subitems[0].author_solution_latex
        self.assertFalse(first.startswith("а)"))
        self.assertIn("1)~найдём нули", first)
        self.assertIn("2)~найдём минимум", first)

    def test_nested_letter_list_stays_inside_solution_subitem(self):
        task_text = "\n".join([
            "1.1.A01 Выполните:",
            r"\\ а) первый пункт;",
            r"\\ б) второй пункт.",
        ])
        solution_text = "\n".join([
            r"\subsection*{1.1.A01}",
            r"\begin{itemize}",
            r"\item[а)] Первое решение:",
            r"\begin{itemize}",
            r"\item[в)] вложенный случай.",
            r"\end{itemize}",
            r"\item[б)] Второе решение.",
            r"\end{itemize}",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        self.assertEqual(len(tasks[0].subitems), 2)
        self.assertIn(
            "в)~вложенный случай",
            tasks[0].subitems[0].author_solution_latex)
        self.assertEqual(
            tasks[0].subitems[1].author_solution_latex,
            "Второе решение.")

    def test_solution_subitems_drop_bare_linebreaks_at_edges(self):
        task_text = "\n".join([
            "1.1.A01 Вычислите:",
            r"\item[а)] первое;",
            r"\item[б)] второе.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\\",
            r"\item[а)] \\ Первое решение. \\",
            r"\item[б)] Второе решение. \\",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        task = tasks[0]
        self.assertEqual(task.author_solution_latex, "")
        self.assertEqual(
            [item.author_solution_latex for item in task.subitems],
            ["Первое решение.", "Второе решение."],
        )

    def test_solution_preserves_common_instruction_before_all_subitems(self):
        task_text = '\n'.join([
            '1.1.A01 Вычислите:',
            r'\item[а)] $2+2$;',
            r'\item[б)] $3+3$.',
        ])
        instruction = 'Для обоих пунктов используйте распределительный закон.'
        solution_text = '\n'.join([
            '1.1.A01 ' + instruction,
            r'\item[а)] Первое решение.',
            r'\item[б)] Второе решение.',
        ])
        tasks, _ = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].author_solution_latex, instruction)
        self.assertEqual(
            [item.author_solution_latex for item in tasks[0].subitems],
            ['Первое решение.', 'Второе решение.'])

    def test_solution_subitem_count_mismatch_is_not_distributed(self):
        task_text = "\n".join([
            "1.1.A01 Вычислите:",
            r"\item[а)] первое;",
            r"\item[б)] второе.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\item[а)] Решение первого.",
            r"\item[б)] Решение второго.",
            r"\item[в)] Лишний распознанный пункт.",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        task = tasks[0]
        self.assertTrue(task.author_solution_latex)
        self.assertTrue(all(
            not item.author_solution_latex for item in task.subitems))
        self.assertIn(
            "Не совпали подпункты условия и решения", task.warnings)

    def test_solution_with_different_label_family_is_not_distributed(self):
        task_text = "\n".join([
            "1.1.A01 Докажите:",
            r"\item[а)] первое утверждение;",
            r"\item[б)] второе утверждение.",
        ])
        solution_text = "\n".join([
            "1.1.A01",
            r"\item[1)] Первый шаг общего доказательства.",
            r"\item[2)] Второй шаг общего доказательства.",
        ])

        tasks, _ = parse_shestakov(task_text, solution_text)

        task = tasks[0]
        self.assertTrue(task.author_solution_latex)
        self.assertTrue(all(
            not item.author_solution_latex for item in task.subitems))
        self.assertIn(
            "Не совпали подпункты условия и решения", task.warnings)

    def test_solution_section_and_list_markup_does_not_leak(self):
        task_text = "\n".join([
            "1.1.A01 Первая задача.",
            "1.1.A02 Вторая задача.",
        ])
        solution_text = "\n".join([
            r"\subsection*{1.1.A01}",
            r"\begin{itemize}",
            r"\item[а)] Первый пункт.",
            r"\item[б)] Второй пункт.",
            r"\end{itemize}",
            r"\subsection*{1.1.A02}",
            "Другое решение.",
        ])
        tasks, _ = parse_shestakov(task_text, solution_text)
        first = tasks[0].author_solution_latex
        self.assertNotIn(r"\item", first)
        self.assertNotIn(r"\subsection", first)
        self.assertFalse(first.startswith("}"))
        self.assertIn("а)~Первый пункт", first)
        self.assertIn("б)~Второй пункт", first)

    def test_missing_task_solution_still_limits_previous_solution(self):
        task_text = "\n".join([
            "8.1.D04 Первая задача.",
            "8.1.D07 Следующая распознанная задача.",
        ])
        solution_text = "\n".join([
            r"\subsection*{8.1.D04}",
            "Решение D04.",
            r"\subsection*{8.1.D05}",
            "Решение нераспознанной D05.",
            r"\subsection*{8.1.D06}",
            "Решение нераспознанной D06.",
            r"\subsection*{8.1.D07}",
            "Решение D07.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].author_solution_latex, "Решение D04.")
        self.assertEqual(tasks[1].author_solution_latex, "Решение D07.")
        self.assertEqual(
            diagnostics["ignored_solution_code_refs"],
            ["8.1.D05", "8.1.D06"],
        )
        self.assertEqual(
            diagnostics["unmatched_solution_ids"],
            ["8.1.D05", "8.1.D06"],
        )

    def test_missing_solution_boundary_warns_previous_task(self):
        task_text = "\n".join([
            "10.1.C04 Первая задача.",
            "10.1.C05 Вторая задача.",
        ])
        solution_text = "\n".join([
            "10.1.C04 Решение C04.",
            "Склеенное начало решения C05.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertTrue(any(
            "10.1.C05" in warning for warning in tasks[0].warnings))
        self.assertEqual(
            diagnostics["solution_boundary_review_predecessors"],
            {"10.1.C04": ["10.1.C05"]},
        )

    def test_solution_image_is_added_to_task_assets(self):
        task_text = "10.1.C04 Задача с чертежом в решении."
        solution_text = "\n".join([
            r"\begin{itemize}",
            r"\captionsetup{labelformat=empty}",
            r"\caption{10.1.C04}",
            r"\includegraphics[max width=\textwidth]{solution-figure}",
            r"\caption{$y=\frac{1}{x}$}",
            "Решение.",
            r"\end{itemize}",
        ])
        tasks, _ = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].images, ["solution-figure"])
        self.assertIn(
            r"\taskpic{1}",
            tasks[0].author_solution_latex,
        )
        self.assertNotIn(
            r"\includegraphics", tasks[0].author_solution_latex)
        self.assertNotIn(
            r"\caption", tasks[0].author_solution_latex)

    def test_task_float_becomes_numbered_taskpic(self):
        task_text = "\n".join([
            "7.1.D03 Сравните:",
            r"\ а) Первый график.",
            r"\ б) Второй график.",
            r"\begin{figure}[h]",
            r"\begin{center}",
            r"\includegraphics[max width=\textwidth]{graph-one}",
            r"\captionsetup{labelformat=empty}",
            r"\caption{Рис. 1}",
            r"\end{center}",
            r"\end{figure}",
        ])
        tasks, _ = parse_shestakov(task_text, "")
        task = tasks[0]
        combined = "\n".join(
            [task.text_latex] + [item.text_latex for item in task.subitems])
        self.assertEqual(task.images, ["graph-one"])
        self.assertIn(r"\taskpic{1}", combined)
        self.assertNotIn(r"\includegraphics", combined)
        self.assertNotIn(r"\begin{figure}", combined)
        self.assertNotIn("\n\n", combined)

    def test_ocr_includegraphics_without_closing_brace_is_extracted(self):
        body = (
            r"$\includegraphics[alt={}$,$max width=\textwidth]"
            r"{8cbf1c7f-38c0-42a9-b381-acfbab07c546-119_484_486_484_100"
            "\n"
            r"\caption{$Рис. 25.}"
        )
        self.assertEqual(extract_images(body), [
            "8cbf1c7f-38c0-42a9-b381-acfbab07c546-119_484_486_484_100",
        ])

    def test_ziv_ocr_figure_in_answer_becomes_taskpic(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{10. Графики}
Вариант 7
\begin{itemize}
  \item[3.] Постройте графики функций:
  \item[а)] \(y=x\)
  \item[б)] \(y=|x|\)
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{10. Графики}
Вариант 7
\begin{itemize}
  \item[3.]
  \item[а)] см. рис. 25
  \item[б)] см. рис. 26
\begin{figure}[h]
\begin{center}
$\includegraphics[alt={}$,$max width=\textwidth]{uuid-fig-25
\captionsetup{labelformat=empty}
\caption{$Рис. 25.}
\end{center}
\end{figure}
\begin{figure}[h]
\begin{center}
$\includegraphics[alt={}$,$max width=\textwidth]{uuid-fig-26
\captionsetup{labelformat=empty}
\caption{$Рис. 26.}
\end{center}
\end{figure}
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "sr/10/v7/3")
        self.assertEqual(task.images, ["uuid-fig-25", "uuid-fig-26"])
        self.assertEqual(
            [item.author_answer_latex for item in task.subitems],
            [r"см. рис." + "\n" + r"\taskpic{1}",
             r"см. рис." + "\n" + r"\taskpic{2}"],
        )
        combined = "\n".join(
            [task.author_answer_latex, task.author_solution_latex]
            + [item.author_answer_latex for item in task.subitems]
            + [item.author_solution_latex for item in task.subitems]
        )
        self.assertNotIn(r"\includegraphics", combined)
        self.assertNotIn(r"\begin{figure}", combined)
        self.assertNotIn("uuid-fig-25", combined)
        self.assertNotIn("рис. 25", combined)
        self.assertNotIn("рис. 26", combined)

    def test_ziv_see_fig_answer_does_not_keep_next_task(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{10. Графики}
Вариант 7
\begin{itemize}
  \item[3.] Постройте графики функций:
  \item[а)] \(y=x\)
  \item[б)] \(y=|x|\)
  \item[4.] Сколько решений в зависимости от параметра \(a\)?
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{10. Графики}
Вариант 7
\begin{itemize}
  \item[3.]
  \item[а)] см. рис. 25
  \item[б)] см. рис. 26. 4. Если \(a \geqslant 2\), то решений нет; если \(-2 \leqslant a<2\), то 1 решение; если \(a<-2\), то 2 решения.
\begin{figure}[h]
\begin{center}
$\includegraphics[alt={}$,$max width=\textwidth]{uuid-fig-25
\caption{$Рис. 25.}
\end{center}
\end{figure}
\begin{figure}[h]
\begin{center}
$\includegraphics[alt={}$,$max width=\textwidth]{uuid-fig-26
\caption{$Рис. 26.}
\end{center}
\end{figure}
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        graph = by_id["sr/10/v7/3"]
        following = by_id["sr/10/v7/4"]
        self.assertEqual(graph.images, ["uuid-fig-25", "uuid-fig-26"])
        self.assertIn(r"\taskpic{1}", graph.subitems[0].author_answer_latex)
        self.assertIn(r"\taskpic{2}", graph.subitems[1].author_answer_latex)
        self.assertEqual(
            graph.subitems[0].author_answer_latex.split("\n", 1)[0],
            "см. рис.")
        self.assertNotIn("Если", graph.subitems[1].author_answer_latex)
        self.assertIn("Если", following.author_answer_latex)
        self.assertIn("2 решения", following.author_answer_latex)
        self.assertNotIn(r"\taskpic", following.author_answer_latex)

    def test_existing_taskpic_is_included_in_assets_and_renumbered(self):
        task_text = "\n".join([
            "7.1.D03 Задача с рисунками.",
            r"\taskpic{already-normalized.png}",
            r"\includegraphics{second-image.jpg}",
        ])
        tasks, _ = parse_shestakov(task_text, "")
        self.assertEqual(
            tasks[0].images,
            ["already-normalized.png", "second-image.jpg"],
        )
        self.assertIn(r"\taskpic{1}", tasks[0].text_latex)
        self.assertIn(r"\taskpic{2}", tasks[0].text_latex)

    def test_solution_reference_to_task_code_is_not_a_marker(self):
        task_text = "\n".join([
            "1.1.A01 Первая задача.",
            "1.1.A02 Вторая задача.",
        ])
        solution_text = "\n".join([
            "1.1.A01 Ответ: смотрите задачу 1.1.A02",
            "и получаем ответ 1.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertIn("1.1.A02", tasks[0].author_solution_latex)
        self.assertEqual(tasks[1].author_solution_latex, "")
        self.assertEqual(diagnostics["matched_solutions"], 1)

    def test_shestakov_keeps_full_solution_without_explicit_answer(self):
        task_text = "1.1.A01 Докажите тождество."
        solution_text = "1.1.A01 Раскроем скобки и приведём подобные."
        tasks, _ = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].author_answer_latex, "")
        self.assertEqual(
            tasks[0].author_solution_latex,
            "Раскроем скобки и приведём подобные.")

    def test_full_solution_drops_only_edge_linebreaks(self):
        task_text = "1.1.A01 Исследуйте функцию."
        solution_text = "1.1.A01\n\\\\\nПервая строка.\\\\\nВторая строка.\\\\"
        tasks, _ = parse_shestakov(task_text, solution_text)
        solution = tasks[0].author_solution_latex
        self.assertFalse(solution.startswith(r"\\"))
        self.assertFalse(solution.endswith(r"\\"))
        self.assertIn(r"Первая строка.\\", solution)

    def test_shestakov_trims_exam_appendices_after_last_task(self):
        task_text = "\n".join([
            "11.1.D10 Последнее условие.",
            "Экзаменационные работы по алгебре для общеобразовательных классов",
            "Вариант 1. Это не часть задачи.",
        ])
        solution_text = "\n".join([
            "11.1.D10 Последнее решение. Ответ: 3.",
            r"\section*{Приложение 3. Примерные варианты экзаменационных работ}",
            "Издательский хвост 641-00-30.",
        ])
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].text_latex, "Последнее условие.")
        self.assertNotIn("641-00-30", tasks[0].author_solution_latex)
        self.assertTrue(
            diagnostics["tasks_truncated_before_exam_variants"])
        self.assertTrue(
            diagnostics["solutions_truncated_before_exam_variants"])

    def test_ziv_locator_includes_work_topic_and_variant(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{1. Числовые неравенства}
Вариант 1
\begin{itemize}
  \item[1.] Сравните дроби.
  \item[2.] Сравните числа.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[1.] Другое сравнение.
  \item[2.] Ещё одно сравнение.
\end{itemize}
\section*{Контрольные работы}
\section*{1. Неравенства}
Вариант 1
\begin{itemize}
  \item[1.] Решите неравенство.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{1. Числовые неравенства}
Вариант 1
\begin{itemize}
  \item[1.] $\frac{2}{3}<\frac{4}{5}$.
  \item[2.] $x<y$.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[1.] $\frac{1}{2}<\frac{2}{3}$.
  \item[2.] $a<b$.
\end{itemize}
\section*{Контрольные работы}
\section*{1. Неравенства}
Вариант 1
\begin{itemize}
  \item[1.] $x>0$.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["sr/01/v1/1", "sr/01/v1/2", "sr/01/v2/1", "sr/01/v2/2",
             "kr/01/v1/1"],
        )
        self.assertEqual(tasks[0].source_path, [
            "Самостоятельные работы", "Числовые неравенства", "Вариант 1",
        ])
        self.assertEqual(tasks[0].collection_key, "sr/01/v1")
        self.assertEqual(
            tasks[0].author_answer_latex,
            r"$\displaystyle \frac{2}{3}<\frac{4}{5}$")
        self.assertEqual(
            tasks[2].author_answer_latex,
            r"$\displaystyle \frac{1}{2}<\frac{2}{3}$")
        self.assertEqual(tasks[3].author_answer_latex, r"$a<b$")
        self.assertEqual(tasks[4].author_answer_latex, r"$x>0$")
        self.assertEqual(diagnostics["matched_solutions"], 5)
        self.assertEqual(diagnostics["ziv_uneven_variant_topics"], [])

    def test_ziv_task_body_stops_before_next_section(self):
        source = r"""
\section*{Контрольные работы}
\section*{2. Корни}
Вариант 4
\begin{itemize}
  \item[6.] Выполните действия
\[
a+b
\]
\end{itemize}
\section*{3. Степенная функция}
Вариант 1
\begin{itemize}
  \item[1.] Следующая задача.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{2. Корни}
Вариант 4
\begin{itemize}
  \item[6.] 1.
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        first = next(task for task in tasks if task.external_id.endswith('/6'))
        self.assertIn("Выполните действия", first.text_latex)
        self.assertNotIn("Степенная функция", first.text_latex)
        self.assertNotIn("Следующая задача", first.text_latex)

    def test_ziv_second_work_heading_starts_answers(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{1. Числовые неравенства}
Вариант 1
\begin{itemize}
  \item[1.] Сравните дроби.
\end{itemize}
\section*{Контрольные работы}
\section*{1. Неравенства}
Вариант 1
\begin{itemize}
  \item[1.] Решите неравенство.
\end{itemize}
\section*{Самостоятельные работы}
\begin{itemize}
  \item[1.] Числовые неравенства
\end{itemize}
Вариант 1
\begin{itemize}
  \item[1.] $1<2$.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{1. Неравенства}
Вариант 1
\begin{itemize}
  \item[1.] $x>0$.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["sr/01/v1/1", "kr/01/v1/1"])
        self.assertEqual(tasks[0].author_answer_latex, "$1<2$")
        self.assertEqual(tasks[1].author_answer_latex, "$x>0$")
        self.assertEqual(diagnostics["matched_solutions"], 2)
        self.assertEqual(diagnostics["duplicate_task_ids"], [])

    def test_two_column_letter_subitems_are_sorted(self):
        _parent, items = split_subitems("\n".join([
            "Сравните значения выражений:",
            r"а) $\sqrt[6]{47}$ и $\sqrt[3]{7}$",
            r"в) $0,8^{-2,7}$ и $0,8^{-1,4}$",
            r"б) $2^{\frac{1}{2}}$ и $4^{\frac{1}{4}}$",
            r"г) $(1,06)^{-5}$ и 1",
        ]))
        self.assertEqual([item.label for item in items], ["а", "б", "в", "г"])

    def test_imported_task_wraps_bare_math(self):
        task = task_from_block(
            Marker(0, 0, "1"), r"Найдите (-1)^{18}+32", [])
        self.assertIn("$(-1)^{18}+32$", task.text_latex)

    def test_ziv_inline_variant_matches_compact_answers(self):
        source = r"""
\section*{Контрольные работы}
\section*{2. Степень с рациональным показателем}
Вариант 1
\begin{itemize}
  \item[1.] Решите неравенство.
  \item[2.] Найдите значение.
  \item[3.] Сравните значения выражений:
а) $\sqrt[6]{47}$ и $\sqrt[3]{7}$
в) $0,8^{-2,7}$ и $0,8^{-1,4}$
б) $2^{\frac{1}{2}}$ и $4^{\frac{1}{4}}$
г) $(1,06)^{-5}$ и 1
  \item[4.] Упростите.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{2. Степень с рациональным показателем}
Вариант 1. 1. $-2\leqslant x<4$. 2. 4. 3. а) $>$; б) $<$; в) $=$; г) $>$. 4. $x=2$.
"""
        tasks, diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), [
            "kr/02/v1/1", "kr/02/v1/2", "kr/02/v1/3", "kr/02/v1/4",
        ])
        self.assertEqual(by_id["kr/02/v1/1"].author_answer_latex, r"$-2\leqslant x<4$")
        self.assertEqual(by_id["kr/02/v1/2"].author_answer_latex, "4")
        self.assertEqual(
            [item.label for item in by_id["kr/02/v1/3"].subitems],
            ["а", "б", "в", "г"])
        self.assertEqual(
            [item.author_answer_latex for item in by_id["kr/02/v1/3"].subitems],
            [r"$>$", r"$<$", r"$=$", r"$>$"])
        self.assertEqual(by_id["kr/02/v1/4"].author_answer_latex, r"$x=2$")
        self.assertEqual(diagnostics["matched_solutions"], 4)

    def test_ziv_answer_item_heading_starts_next_topic(self):
        source = r"""
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 4
\begin{itemize}
  \item[1.] Решите систему.
\end{itemize}
\section*{2. Степень с рациональным показателем}
Вариант 1
\begin{itemize}
  \item[1.] Решите неравенство.
  \item[5.] Вычислите.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\begin{itemize}
  \item[1.] Уравнения
\end{itemize}
Вариант 4
\begin{itemize}
  \item[1.] $(1;2)$.
\end{itemize}
\begin{enumerate}
  \setcounter{enumi}{1}
  \item Степень с рациональным показателем
\end{enumerate}
Вариант 1
\begin{itemize}
  \item[1.] $-2\leqslant x<4$.
  \item[5.] а) 2; б) -1.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertIn("kr/02/v1/1", by_id)
        self.assertIn("kr/02/v1/5", by_id)
        self.assertEqual(
            by_id["kr/02/v1/1"].author_answer_latex, r"$-2\leqslant x<4$")
        fifth = by_id["kr/02/v1/5"]
        fifth_ans = fifth.author_answer_latex or " ".join(
            item.author_answer_latex for item in fifth.subitems)
        self.assertIn("2", fifth_ans)
        self.assertNotEqual(
            by_id["kr/01/v4/1"].author_answer_latex,
            by_id["kr/02/v1/1"].author_answer_latex)
        self.assertGreaterEqual(diagnostics["matched_solutions"], 3)

    def test_ziv_inline_number_after_figure_ref(self):
        source = r"""
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 1
\begin{itemize}
  \item[3.] Постройте графики.
  \item[4.] Решите уравнения.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 1
\begin{itemize}
  \item[3.] а) см. рис. 29; б) см. рис. 31. 4. а) $\{-3;3\}$; б) $\{0\}$.
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        fourth = by_id["kr/03/v1/4"]
        answers = [item.author_answer_latex for item in fourth.subitems] or [
            fourth.author_answer_latex]
        combined = " ".join(item or "" for item in answers)
        self.assertIn(r"\{-3", combined)
        self.assertNotIn("рис. 31", combined)
        third = by_id["kr/03/v1/3"].author_answer_latex
        self.assertNotIn(r"\{-3", third)

    def test_ziv_compact_answers_cut_glued_next_numbers(self):
        source = r"""
\section*{Контрольные работы}
\section*{5. Формулы сложения}
Вариант 1
\begin{itemize}
  \item[1.] Упростите:
  \item[а)] первое
  \item[б)] второе
  \item[2.] Вычислите.
  \item[3.] Упростите ещё.
  \item[4.] Область определения.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{5. Формулы сложения}
Вариант 1
\begin{enumerate}
  \item а) 1; б) 0. 2. 1. 3. 2. 4. \(\frac{\pi}{2}+\pi k, k \in \mathbb{Z}\).
\end{enumerate}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        first = by_id["kr/05/v1/1"]
        by_label = {item.label: item.author_answer_latex for item in first.subitems}
        second_item = by_label.get("б") or by_label.get("b")
        self.assertEqual(second_item, "0")
        self.assertEqual(by_id["kr/05/v1/2"].author_answer_latex, "1")
        self.assertEqual(by_id["kr/05/v1/3"].author_answer_latex, "2")
        self.assertIn(r"\pi", by_id["kr/05/v1/4"].author_answer_latex)

    def test_ziv_bold_and_glued_decimal_task_numbers(self):
        source = r"""
\section*{Контрольные работы}
\section*{7. Итоговая}
Вариант 2
\begin{itemize}
  \item[6.] Число членов.
  \item[7.] Решите уравнение.
\end{itemize}
Вариант 4
\begin{itemize}
  \item[2.] Решите систему.
  \item[3.] Область определения.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{7. Итоговая}
Вариант 2
\begin{enumerate}
  \item[6.] \(n=7.7 .-1\).
\end{enumerate}
Вариант 4
\begin{enumerate}
  \item[2.] \(\left(\frac{12}{5} ; \frac{13}{5}\right) . \mathbf{3 .}(-2 ; 0) \cup(0 ; 3)\).
\end{enumerate}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertIn("7", by_id["kr/07/v2/6"].author_answer_latex)
        self.assertNotIn(".-1", by_id["kr/07/v2/6"].author_answer_latex)
        self.assertIn("-1", by_id["kr/07/v2/7"].author_answer_latex)
        self.assertIn(r"12", by_id["kr/07/v4/2"].author_answer_latex)
        self.assertNotIn("3.", by_id["kr/07/v4/2"].author_answer_latex)
        self.assertIn("-2", by_id["kr/07/v4/3"].author_answer_latex)

    def test_ziv_compact_answers_split_after_closed_formula(self):
        source = r"""
\section*{Контрольные работы}
\section*{4. Тригонометрические функции}
Вариант 2
\begin{itemize}
  \item[2.] Вычислите значения тригонометрических функций, если:
а) \(\displaystyle \cos \alpha=\frac{3}{5} ; \frac{3 \pi}{2}<\alpha<2 \pi\)
б) \(\displaystyle \operatorname{tg} \alpha=-\frac{3}{4} ; \frac{\pi}{2}<\alpha<\pi\)
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{4. Тригонометрические функции}
Вариант 2. 2. \(\displaystyle \sin \alpha=-\frac{4}{5} ; \operatorname{tg} \alpha=-\frac{4}{3}\); \(\displaystyle \operatorname{ctg} \alpha=-\frac{3}{4} ;\) б) \(\displaystyle \cos \alpha=-\frac{4}{5} ; \sin \alpha=\frac{3}{5} ; \operatorname{ctg} \alpha=-\frac{4}{3}\)
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "kr/04/v2/2")
        self.assertEqual([item.label for item in task.subitems], ["а", "б"])
        answers = [item.author_answer_latex for item in task.subitems]
        self.assertIn(r"\sin \alpha", answers[0])
        self.assertNotIn("б)", answers[0])
        self.assertIn(r"\cos \alpha", answers[1])
        self.assertEqual(task.author_answer_latex, "")

    def test_ziv_compact_answer_does_not_keep_next_task_number(self):
        source = r"""
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 3
\begin{itemize}
  \item[1.] Решите системы:
а) \(x+y=5\)
б) \(x-y=1\)
  \item[2.] Решите уравнение.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 3. 1. а) $(2;3)$ б) $(-1,75;-3);\left(-\frac{7}{6};-2\right)$.2 .$\left\{\frac{5}{4};3\right\}$.
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        first = by_id["kr/01/v3/1"]
        second = by_id["kr/01/v3/2"]
        glued = " ".join(
            [first.author_answer_latex]
            + [item.author_answer_latex for item in first.subitems])
        self.assertNotIn(".2 .", glued)
        self.assertNotIn("2 .", glued)
        self.assertTrue(
            second.author_answer_latex
            or any(item.author_answer_latex for item in second.subitems))
        self.assertIn(r"\frac{5}{4}", second.author_answer_latex)

    def test_reattach_cuts_ocr_task_number_before_dollar(self):
        from problems.textbook_parser import (
            SubitemDraft, reattach_leaked_following_answers)
        first = type("Draft", (), {
            "external_id": "kr/01/v3/1",
            "author_answer_latex": "",
            "author_solution_latex": "",
            "subitems": [
                SubitemDraft("а", "система", author_answer_latex=r"$(2;3)$"),
                SubitemDraft(
                    "б", "система",
                    author_answer_latex=(
                        r"(-1,75 ;-3) ;$\displaystyle \left(-\frac{7}{6}$ "
                        r";$-2\right)$ .2 .$\displaystyle \left\{\frac{5}{4}$ "
                        r"; $3\right\}$)$"),
                ),
            ],
        })()
        second = type("Draft", (), {
            "external_id": "kr/01/v3/2",
            "author_answer_latex": "",
            "author_solution_latex": "",
            "subitems": [],
        })()
        changed = reattach_leaked_following_answers([first, second])
        self.assertTrue(changed)
        kept = first.subitems[1].author_answer_latex
        self.assertNotIn(".2 .", kept)
        self.assertNotIn(r"\left(-\frac{7}{6}$", kept)
        self.assertIn(r"\left(-\frac{7}{6}", kept)
        self.assertIn(r"\frac{5}{4}", second.author_answer_latex)
        self.assertFalse(second.author_answer_latex.endswith(")"))

    def test_ziv_inline_variant_and_tilde_numbers_do_not_leak(self):
        # OCR Зива часто пишет «Вариант 2\\» и «1.~» без \item: иначе
        # последний пункт варианта 1 захватывает чужие варианты в подпункт.
        source = r"""
\section*{Самостоятельные работы}
\section*{9. Область определения функции. Возрастание и убывание функции}
Вариант 1
\begin{itemize}
  \item[1.] Выясните, является ли функция четной или нечетной:
а) \(f(x)=3 x^{4}-1\),
б) \(f(x)=5 x^{3}-2 x\).
  \item[2.] Не строя графиков функций, найдите точки их пересечения \(y=-\frac{12}{x}\) и \(y=x-7\).
  \item[3.] Постройте графики функций:
а) \(y=\frac{4}{x}+1\),
б) \(y=-\frac{1}{x-2}+2\).
\end{itemize}
Вариант 2\\
1.~Выясните, является ли функция четной или нечетной:\\
а) \(f(x)=7 x^{3}\),\\
б) \(f(x)=17 x^{2}-5 x^{4}\).
2.~Не строя графиков функций, найдите точки их пересечения \(y=\frac{8}{x}\) и \(y=x+2\).
3.~Постройте графики функций:\\
а) \(y=-\frac{x}{4}-1\),\\
б) \(y=\frac{2}{x+2}-1\).
Вариант 3\\
1.~Исследуйте функции на четность:\\
а) \(f(x)=\frac{1}{7 x-5}\).
Вариант 4\\
1.~Определите четность:\\
а) \(f(x)=x^{3}\).
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{9. Область определения функции. Возрастание и убывание функции}
Вариант 1
\begin{itemize}
  \item[1.] четная.
  \item[2.] $(-3;4)$.
  \item[3.] графики.
\end{itemize}
Вариант 2. 1. нечетная. 2. $(-2; -4)$. 3. графики.
Вариант 3. 1. ни четная, ни нечетная.
Вариант 4. 1. нечетная.
"""
        tasks, diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), [
            "sr/09/v1/1", "sr/09/v1/2", "sr/09/v1/3",
            "sr/09/v2/1", "sr/09/v2/2", "sr/09/v2/3",
            "sr/09/v3/1", "sr/09/v4/1",
        ])
        leaked = by_id["sr/09/v1/3"]
        self.assertIn(r"y=\frac{4}{x}+1", leaked.text_latex + "".join(
            item.text_latex for item in leaked.subitems))
        joined = "\n".join(
            [leaked.text_latex] + [item.text_latex for item in leaked.subitems])
        self.assertNotIn("Вариант 2", joined)
        self.assertNotIn("Выясните", joined)
        self.assertNotIn("Исследуйте", joined)
        self.assertIn("четной или нечетной", by_id["sr/09/v2/1"].text_latex)
        self.assertIn(r"y=\frac{8}{x}", by_id["sr/09/v2/2"].text_latex)
        self.assertEqual(
            [item.label for item in by_id["sr/09/v2/3"].subitems],
            ["а", "б"])
        self.assertEqual(by_id["sr/09/v1/3"].author_answer_latex, "графики")
        self.assertEqual(by_id["sr/09/v2/1"].author_answer_latex, "нечетная")
        self.assertEqual(diagnostics["matched_solutions"], 8)
        self.assertEqual(diagnostics["ziv_uneven_variant_topics"], [])

    def test_ziv_setcounter_and_bare_stems_split_tasks(self):
        # После \item[1.] OCR Зива часто теряет номера и пишет
        # \setcounter{enumi}{N} плюс новую формулировку с «:».
        source = r"""
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 1
\begin{itemize}
  \item[4.] Решите уравнение $x=1$.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[4.] Решите уравнения:
а) \(\sqrt{x^{2}-9}=4\),
б) \(\sqrt{8-2 x-x^{2}}+x=-4\).
\end{itemize}
Вариант 3
\begin{itemize}
  \item[1.] Исследуйте функции на четность и нечетность:
а) \(f(x)=x^{4}-3 x^{2}+1\),
б) \(f(x)=-2 x|x|+4 x^{3}\).
\setcounter{enumi}{1}
Найдите области определения функций:
а) \(f(x)=\sqrt[3]{\frac{x^{2}}{5-3 x-2 x^{2}}}\),
б) \(f(x)=\sqrt{\frac{x^{2}-5 x+4}{x^{2}+2 x+1}}\).
\setcounter{enumi}{2}
Постройте графики функций:
а) \(y=\sqrt{x-1}\),
б) \(y=\sqrt{x+1}-2\),\\
Найдите промежутки, на которых \(y(x)>0 ; y(x)<0\).
Решите уравнения:
а) \(\sqrt{x+2}=x\),
б) \(\sqrt{4 x-3}=\frac{3 x-1}{\sqrt{3 x-5}}\).
\end{itemize}
Вариант 4
Исследуйте функции на четность и нечетность:
а) \(f(x)=3 x^{3}-x^{7}\),
б) \(f(x)=-x^{2}|x|-3 x^{6}\).
\setcounter{enumi}{1}
Найдите области определения функций:
а) \(f(x)=\sqrt[7]{\frac{x^{6}}{2 x^{2}+7 x+5}}\),
б) \(f(x)=\sqrt{\frac{4 x^{2}+12 x+9}{-x^{2}+6 x-5}}\).
\setcounter{enumi}{2}
Постройте графики функций:
а) \(y=\sqrt{x+1}\),
б) \(y=\sqrt{x-1}+2\),\\
Найдите промежутки, на которых \(y(x)>0 ; y(x)<0\).
Решите уравнения:
а) \(\sqrt{x-1}=x-3\),
б) \(\sqrt{4 x-11}=\frac{2 x-2}{\sqrt{3 x+7}}\).
\section*{4. Основные тригонометрические тождества}
Вариант 1
\begin{itemize}
  \item[1.] Упростите выражение.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 1
\begin{itemize}
  \item[4.] $1$.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[4.] $4$.
\end{itemize}
Вариант 3
\begin{itemize}
  \item[1.] четная.
  \item[2.] $x\geqslant 0$.
  \item[3.] графики.
  \item[4.] $x=2$.
\end{itemize}
Вариант 4
\begin{itemize}
  \item[1.] нечетная.
  \item[2.] $x>0$.
  \item[3.] графики.
  \item[4.] $x=4$.
\end{itemize}
\section*{4. Основные тригонометрические тождества}
Вариант 1
\begin{itemize}
  \item[1.] $1$.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), [
            "kr/03/v1/4", "kr/03/v2/4",
            "kr/03/v3/1", "kr/03/v3/2", "kr/03/v3/3", "kr/03/v3/4",
            "kr/03/v4/1", "kr/03/v4/2", "kr/03/v4/3", "kr/03/v4/4",
            "kr/04/v1/1",
        ])
        first = by_id["kr/03/v3/1"]
        joined = "\n".join(
            [first.text_latex] + [item.text_latex for item in first.subitems])
        self.assertIn("четность", first.text_latex)
        self.assertNotIn("Вариант 4", joined)
        self.assertNotIn("Найдите области", joined)
        self.assertNotIn("Решите уравнения", joined)
        self.assertNotIn("тригонометрические", joined)
        self.assertIn("области определения", by_id["kr/03/v3/2"].text_latex)
        self.assertIn("Постройте графики", by_id["kr/03/v3/3"].text_latex)
        self.assertIn("промежутки", "\n".join(
            item.text_latex for item in by_id["kr/03/v3/3"].subitems))
        self.assertNotIn("setcounter", "\n".join(
            [by_id["kr/03/v3/1"].text_latex]
            + [item.text_latex for item in by_id["kr/03/v3/1"].subitems]))
        self.assertIn("Решите уравнения", by_id["kr/03/v3/4"].text_latex)
        self.assertIn("четность", by_id["kr/03/v4/1"].text_latex)
        self.assertIn("Решите уравнения", by_id["kr/03/v4/4"].text_latex)
        self.assertNotIn("тригонометрические", by_id["kr/03/v4/4"].text_latex)
        self.assertEqual(by_id["kr/03/v2/4"].author_answer_latex, "$4$")
        self.assertEqual(by_id["kr/03/v3/4"].author_answer_latex, "$x=2$")
        self.assertEqual(by_id["kr/03/v4/1"].author_answer_latex, "нечетная")
        self.assertEqual(diagnostics["matched_solutions"], 11)
        self.assertEqual(diagnostics["ziv_uneven_variant_topics"], [])

    def test_ziv_solve_stem_after_graph_prompt_is_a_new_task(self):
        source = r"""
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 3
\begin{itemize}
  \item[3.] Постройте графики функций:
а) \(y=\sqrt{x-1}\),
б) \(y=\sqrt{x+1}-2\),\\
Найдите промежутки, на которых \(y(x)>0 ; y(x)<0\). Решите уравнения:
а) \(\sqrt{x+2}=x\),
б) \(\sqrt{4 x-3}=1\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{3. Степенная функция}
Вариант 3
\begin{itemize}
  \item[3.] графики.
  \item[4.] $x=2$.
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), ["kr/03/v3/3", "kr/03/v3/4"])
        joined = "\n".join(
            [by_id["kr/03/v3/3"].text_latex]
            + [item.text_latex for item in by_id["kr/03/v3/3"].subitems])
        self.assertIn("Постройте", by_id["kr/03/v3/3"].text_latex)
        self.assertNotIn("Решите уравнения", joined)
        self.assertIn("Решите уравнения", by_id["kr/03/v3/4"].text_latex)
        self.assertEqual(
            [item.label for item in by_id["kr/03/v3/4"].subitems],
            ["а", "б"])

    def test_ziv_uneven_variant_counts_warn_about_merged_tasks(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{9. Функции}
Вариант 1
\begin{itemize}
  \item[1.] Первая.
  \item[2.] Вторая.
  \item[3.] Третья и хвост следующих вариантов.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[1.] Только одна задача.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{9. Функции}
Вариант 1
\begin{itemize}
  \item[1.] 1.
  \item[2.] 2.
  \item[3.] 3.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[1.] 1.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["sr/09/v1/1", "sr/09/v1/2", "sr/09/v1/3", "sr/09/v2/1"])
        self.assertEqual(diagnostics["ziv_uneven_variant_topics"], [{
            "topic": "sr/09",
            "variants": {"v1": 3, "v2": 1},
        }])
        self.assertTrue(all(
            ZIV_UNEVEN_VARIANT_WARNING in task.warnings for task in tasks))

    def test_ziv_paired_variant_counts_are_accepted(self):
        source = r"""
\section*{Контрольные работы}
\section*{2. Степени}
Вариант 1
\begin{itemize}
  \item[1.] A.
  \item[2.] B.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[1.] C.
  \item[2.] D.
\end{itemize}
Вариант 3
\begin{itemize}
  \item[1.] E.
\end{itemize}
Вариант 4
\begin{itemize}
  \item[1.] F.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{2. Степени}
Вариант 1
\begin{itemize}
  \item[1.] 1.
  \item[2.] 2.
\end{itemize}
Вариант 2
\begin{itemize}
  \item[1.] 3.
  \item[2.] 4.
\end{itemize}
Вариант 3
\begin{itemize}
  \item[1.] 5.
\end{itemize}
Вариант 4
\begin{itemize}
  \item[1.] 6.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        self.assertEqual(diagnostics["ziv_uneven_variant_topics"], [])
        self.assertFalse(any(
            ZIV_UNEVEN_VARIANT_WARNING in task.warnings for task in tasks))

    def test_ziv_answers_default_variant_and_title_match(self):
        source = r"""
\section*{Контрольные работы}
\section*{2. Корни}
Вариант 1
\begin{itemize}
  \item[1.] Найдите корень.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Контрольные работы}
\section*{Корни}
1. $3$.
"""
        tasks, diagnostics = parse_ziv(source)
        self.assertEqual(tasks[0].external_id, "kr/02/v1/1")
        self.assertEqual(tasks[0].author_answer_latex, "$3$")
        self.assertEqual(diagnostics["matched_solutions"], 1)

    def test_ziv_trims_section_and_work_heading_from_last_task(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{1. Неравенства}
Вариант 1
\begin{itemize}
  \item[1.] Сравните числа.
  \item[2.] Решите неравенство $x>0$.
\end{itemize}
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 1
\begin{itemize}
  \item[1.] Решите уравнение.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{1. Неравенства}
Вариант 1
\begin{itemize}
  \item[1.] $1<2$.
  \item[2.] $x>0$.
\end{itemize}
\section*{Контрольные работы}
\section*{1. Уравнения}
Вариант 1
\begin{itemize}
  \item[1.] $x=1$.
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        last = by_id["sr/01/v1/2"]
        joined = "\n".join(
            [last.text_latex] + [item.text_latex for item in last.subitems])
        self.assertIn("неравенство", last.text_latex)
        self.assertNotIn("Контрольн", joined)
        self.assertNotIn("Уравнения", joined)
        self.assertNotIn("Вариант", joined)
        self.assertEqual(by_id["kr/01/v1/1"].text_latex, "Решите уравнение.")

    def test_split_subitems_trims_variant_heading_from_last_item(self):
        parent, items = split_subitems("\n".join([
            "Постройте графики функций:",
            r"а) \(y=\frac{4}{x}+1\)",
            r"б) \(y=-\frac{1}{x-2}+2\).",
            r"Вариант 2",
            r"1.~Выясните, является ли функция четной.",
        ]))
        self.assertEqual(parent, "Постройте графики функций:")
        self.assertEqual([item.label for item in items], ["а", "б"])
        self.assertIn(r"x-2", items[-1].text_latex)
        self.assertNotIn("Вариант", items[-1].text_latex)
        self.assertNotIn("Выясните", items[-1].text_latex)

    def test_display_math_is_not_a_topic_heading(self):
        self.assertFalse(_ziv_looks_like_topic_title(
            "Постройте график функции\n\\[\ny=\\sin x.\n\\]"))
        self.assertTrue(_ziv_looks_like_topic_title(
            "Неравенства и уравнения, содержащие степень"))
        self.assertFalse(_ziv_looks_like_topic_title("а) 2; б) -1."))
        self.assertFalse(_ziv_looks_like_topic_title(
            r"а) см. рис. 29; б) см. рис. 31."))

    def test_leaked_heading_ignores_work_word_inside_sentence(self):
        kept, tail = split_leaked_structural_tail(
            "Напишите самостоятельную работу по теме.")
        self.assertEqual(tail, "")
        self.assertIn("самостоятельную работу", kept)

    def test_rewalk_splits_setcounter_and_next_variant(self):
        tasks = rewalk_ziv_merged_body(
            "kr/03/v3/1",
            ["Контрольные работы", "Степенная функция", "Вариант 3"],
            "Исследуйте функции на четность и нечетность:",
            [
                {"label": "а", "text_latex": r"\(f(x)=x^{4}-3 x^{2}+1\)"},
                {"label": "б", "text_latex": "\n".join([
                    r"\(f(x)=-2 x|x|+4 x^{3}\).",
                    r"\setcounter{enumi}{1}",
                    "Найдите области определения функций:",
                    r"а) \(f(x)=\sqrt{x}\),",
                    r"б) \(f(x)=\sqrt{x+1}\).",
                    r"Вариант 4",
                    "Исследуйте функции на четность и нечетность:",
                    r"а) \(f(x)=3 x^{3}\).",
                ])},
            ],
            collection_title="Степенная функция",
        )
        by_id = {task.external_id: task for task in tasks}
        self.assertIn("kr/03/v3/1", by_id)
        self.assertIn("kr/03/v3/2", by_id)
        self.assertIn("kr/03/v4/1", by_id)
        first = by_id["kr/03/v3/1"]
        joined = "\n".join(
            [first.text_latex] + [item.text_latex for item in first.subitems])
        self.assertIn("четность", first.text_latex)
        self.assertNotIn("Вариант 4", joined)
        self.assertNotIn("Найдите области", joined)
        self.assertIn("области определения", by_id["kr/03/v3/2"].text_latex)
        self.assertIn("четность", by_id["kr/03/v4/1"].text_latex)

    def test_ziv_shared_prompt_before_numbered_list_is_not_a_task(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{2. Уравнения}
Вариант 1
\begin{itemize}
  \item[5.] \(x^{2}=1\).
\end{itemize}
Вариант 2\\
Решите уравнения 1-5:
1.~\(x^{2}=4\).
2.~\(x^{2}=9\).
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{2. Уравнения}
Вариант 1
\begin{itemize}
  \item[5.] $1$.
\end{itemize}
Вариант 2. 1. $\pm2$. 2. $\pm3$.
"""
        tasks, _diagnostics = parse_ziv(source)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["sr/02/v1/5", "sr/02/v2/1", "sr/02/v2/2"])
        self.assertIn(r"x^{2}=4", tasks[1].text_latex)
        self.assertIn("Решите уравнения 1-5", tasks[1].text_latex)
        self.assertIn("Решите уравнения 1-5", tasks[2].text_latex)

    def test_ziv_section_variant_keeps_current_topic(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{4. Решение задач с помощью уравнений}
Вариант 1
\begin{itemize}
  \item[1.] Поезд опоздал.
\end{itemize}
\section*{Вариант 2}
\begin{itemize}
  \item[1.] Лыжник опоздал.
  \item[2.] Найдите два числа.
\end{itemize}
\section*{16. Формулы приведения}
\section*{Вариант 1}
\begin{itemize}
  \item[1.] Приведите \(\sin 304^{\circ}\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{4. Решение задач с помощью уравнений}
Вариант 1
\begin{itemize}
  \item[1.] 80.
\end{itemize}
\section*{Вариант 2}
\begin{itemize}
  \item[1.] 10.
  \item[2.] 1 и 6.
\end{itemize}
\section*{16. Формулы приведения}
\section*{Вариант 1}
\begin{itemize}
  \item[1.] \(\sin 56^{\circ}\).
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(
            sorted(by_id),
            ["sr/04/v1/1", "sr/04/v2/1", "sr/04/v2/2", "sr/16/v1/1"])
        self.assertIn("Лыжник", by_id["sr/04/v2/1"].text_latex)
        self.assertEqual(
            by_id["sr/16/v1/1"].source_path[1], "Формулы приведения")

    def test_ziv_item_heading_starts_next_topic(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{9. Область определения функции}
Вариант 8
\begin{itemize}
  \item[1.] Найдите область определения \(f(x)=\sqrt{x}\).
  \item[10.] Четность и нечетность функции.\\
Функция \(y=\frac{k}{x}\)
\end{itemize}
Вариант 1
\begin{itemize}
  \item[1.] Выясните, является ли функция четной.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{9. Область определения функции}
Вариант 8
\begin{itemize}
  \item[1.] \(x\geqslant 0\).
\end{itemize}
\section*{10. Четность и нечетность функции}
Вариант 1
\begin{itemize}
  \item[1.] четная.
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), ["sr/09/v8/1", "sr/10/v1/1"])
        self.assertIn("область", by_id["sr/09/v8/1"].text_latex)
        self.assertIn("четной", by_id["sr/10/v1/1"].text_latex)

    def test_ziv_mid_variant_topic_leak_does_not_steal_next_variant(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{8. Упражнения на радикалы}
Вариант 7
\begin{enumerate}
  \item Выполните действия: \(a+b\).
\end{enumerate}
\begin{enumerate}
  \setcounter{enumi}{8}
  \item Область определения функции. Возрастание и убывание функции
\end{enumerate}
\begin{enumerate}
  \setcounter{enumi}{1}
  \item Решите уравнения: \(2^{x}=4\).
\end{enumerate}
Вариант 8
\begin{enumerate}
  \item Выполните действия: \(c+d\).
  \setcounter{enumi}{1}
  \item Решите уравнения: \(3^{x}=9\).
\end{enumerate}
\section*{9. Область определения функции}
Вариант 1
\begin{itemize}
  \item[1.] Найдите область определения \(f(x)=\sqrt{x}\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{8. Упражнения на радикалы}
Вариант 7
\begin{itemize}
  \item[1.] \(1\).
  \item[2.] \(2\).
\end{itemize}
Вариант 8
\begin{itemize}
  \item[1.] \(1\).
  \item[2.] \(3\).
\end{itemize}
\section*{9. Область определения функции}
Вариант 1
\begin{itemize}
  \item[1.] \(x\geqslant 0\).
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["sr/08/v7/1", "sr/08/v7/2", "sr/08/v8/1", "sr/08/v8/2",
             "sr/09/v1/1"])
        self.assertIn("Выполните", tasks[2].text_latex)
        self.assertIn("область", tasks[4].text_latex)

    def test_ziv_enumerate_items_and_check_work_are_tasks(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{3. Системы нелинейных уравнений}
Вариант 1\\
Решите системы 1-5:
\begin{enumerate}
  \item \(x+y=1\)
  \item \(x-y=2\)
\end{enumerate}
\section*{Проверочные работы на повторение}
\section*{Проверочная работа № 1}
Вариант 1
\begin{itemize}
  \item[1.] Вычислите \(1+1\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{3. Системы нелинейных уравнений}
Вариант 1
\begin{enumerate}
  \item \(1\).
  \item \(2\).
\end{enumerate}
\section*{Проверочные работы на повторение}
\section*{Проверочная работа № 1}
Вариант 1
\begin{itemize}
  \item[1.] \(2\).
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), ["pr/01/v1/1", "sr/03/v1/1", "sr/03/v1/2"])
        self.assertIn("x+y", by_id["sr/03/v1/1"].text_latex)
        self.assertIn("Решите системы", by_id["sr/03/v1/1"].text_latex)
        self.assertEqual(
            by_id["pr/01/v1/1"].source_path[0], "Проверочные работы на повторение")
        self.assertIn("Вычислите", by_id["pr/01/v1/1"].text_latex)

    def test_ziv_answer_bare_pr_work_number_sets_topic(self):
        source = r"""
\section*{Проверочные работы на повторение}
\section*{Проверочная работа № 1}
Вариант 1
\begin{itemize}
  \item[1.] Вычислите.
  \item[2.] Упростите.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Проверочные работы на повторение}
Проверочная работа № 1\\
Вариант 1
\begin{itemize}
  \item[1.] $-1$.
  \item[2.] $0$.
\end{itemize}
"""
        tasks, diagnostics = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["pr/01/v1/1"].author_answer_latex, "$-1$")
        self.assertEqual(by_id["pr/01/v1/2"].author_answer_latex, "$0$")
        self.assertGreaterEqual(diagnostics["matched_solutions"], 2)

    def test_ziv_strips_trailing_dot_from_section_title(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{11. Чётные и нечётные функции.}
Вариант 1
\begin{itemize}
  \item[1.] Является ли функция четной.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{11. Чётные и нечётные функции.}
Вариант 1
\begin{itemize}
  \item[1.] четная.
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        self.assertEqual(
            tasks[0].source_path[1], 'Чётные и нечётные функции')
        self.assertEqual(tasks[0].author_answer_latex, 'четная')

    def test_ziv_bare_enumerate_after_setcounter_continues_numbering(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{13. Тригонометрические тождества}
Вариант 3
\begin{itemize}
  \item[1.] Дано: \(\operatorname{tg} \alpha=1\). Найдите \(\sin \alpha\).
\end{itemize}
\begin{enumerate}
  \setcounter{enumi}{1}
  \item Упростите \(\sin \alpha\).
  \item Дано: \(\sin \alpha+\cos \alpha=1\).
  \item Найдите \(\operatorname{tg} \alpha\).
  \item Решите уравнения: \(x=0\).
\end{enumerate}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{13. Тригонометрические тождества}
Вариант 3
\begin{itemize}
  \item[1.] \(1\).
  \item[2.] \(\sin\).
  \item[3.] \(1\).
  \item[4.] \(1\).
  \item[5.] \(0\).
\end{itemize}
"""
        tasks, _diagnostics = parse_ziv(source)
        self.assertEqual(
            [task.external_id for task in tasks],
            ["sr/13/v3/1", "sr/13/v3/2", "sr/13/v3/3",
             "sr/13/v3/4", "sr/13/v3/5"])
        self.assertIn("Упростите", tasks[1].text_latex)
        self.assertIn("Найдите", tasks[3].text_latex)

    def test_galitsky_missing_answer_is_not_a_warning(self):
        source = r"""
\section*{§ 1. ДРОБИ}
\item[1.1.] Вычислите $1+1$.
\item[1.2.] Докажите тождество.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. 2.
"""
        tasks, diagnostics = parse_galitsky(source)
        self.assertEqual(diagnostics["matched_solutions"], 1)
        self.assertEqual(tasks[0].author_answer_latex, "2")
        self.assertEqual(tasks[1].author_answer_latex, "")
        self.assertFalse(any(
            "Не найден авторский ответ/решение" in warning
            for warning in tasks[1].warnings))

    def test_ziv_leading_star_is_not_part_of_statement(self):
        source = r"""
\section*{Проверочные работы}
\section*{Проверочная работа № 1}
Вариант 1
\begin{itemize}
  \item[5.] * Упростите выражение \(x+x\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Проверочные работы}
Проверочная работа № 1\\
Вариант 1
\begin{itemize}
  \item[5.] 0.
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "pr/01/v1/5")
        self.assertFalse(task.text_latex.lstrip().startswith("*"))
        self.assertIn("Упростите", task.text_latex)
        self.assertEqual(task.stars, 1)

    def test_ziv_nested_first_letter_stays_a_subitem(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{5. Степень}
Вариант 1
\begin{itemize}
  \item[1.] Вычислите:
  \begin{itemize}
    \item[а)] \(1+1\),
  \end{itemize}
б) \(2+2\),
в) \(3+3\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{5. Степень}
Вариант 1
\begin{itemize}
  \item[1.] а) 2; б) 4; в) 6.
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "sr/05/v1/1")
        self.assertEqual(
            [item.label for item in task.subitems], ["а", "б", "в"])
        self.assertNotIn("а)", task.text_latex)

    def test_ziv_decimal_comma_is_not_a_subitem(self):
        parent, items = split_subitems(
            r"Вычислите: а) \(1+1\), б) \((0,6)^{-2}\).")
        self.assertEqual([item.label for item in items], ["а", "б"])
        self.assertIn(r"(0,6)^{-2}", items[1].text_latex)

    def test_ziv_skips_missing_answer_number_and_peels_later(self):
        source = r"""
\section*{Проверочные работы}
\section*{Проверочная работа № 1}
Вариант 1
\begin{itemize}
  \item[1.] Первая.
  \item[4.] Четвёртая.
  \item[5.] Пятая.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Проверочные работы}
Проверочная работа № 1\\
Вариант 1
\begin{itemize}
  \item[1.] -1,1. 4. 0. 5.1. Решение: \(x=1\).
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertIn("0", by_id["pr/01/v1/4"].author_answer_latex)
        self.assertNotIn("5.", by_id["pr/01/v1/4"].author_answer_latex)
        fifth = by_id["pr/01/v1/5"].author_answer_latex
        self.assertTrue(fifth)
        self.assertIn("1", fifth)

    def test_ziv_numbered_parts_become_subitems(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{16. Формулы приведения}
Вариант 1
\begin{itemize}
  \item[1.] 1) Приведите, сохранив наименование:\\
а) \(\sin 304^{\circ}\),\\
б) \(\cos 3,6 \pi\).
  \begin{itemize}
    \item[2)] Приведите, изменив наименование:\\
а) \(\operatorname{tg} 278^{\circ}\),\\
б) \(\sin (-3,1) \pi\).
    \item[3)] Вычислите:\\
а) \(\sin 930^{\circ}\),\\
б) \(\operatorname{tg} \frac{5 \pi}{6}\).
  \end{itemize}
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{16. Формулы приведения}
Вариант 1
\begin{itemize}
  \item[1.] а) 1; б) 2.
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "sr/16/v1/1")
        self.assertEqual([item.label for item in task.subitems], ["1", "2", "3"])
        self.assertIn("сохранив", task.subitems[0].text_latex)
        self.assertIn("изменив", task.subitems[1].text_latex)
        self.assertIn("Вычислите", task.subitems[2].text_latex)

    def test_ziv_numbered_part_answers_fill_subitems(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{16. Формулы приведения}
Вариант 1
\begin{itemize}
  \item[1.] 1) Приведите, сохранив наименование:\\
а) \(\sin 304^{\circ}\).
  \begin{itemize}
    \item[2)] Приведите, изменив наименование:\\
а) \(\operatorname{tg} 278^{\circ}\).
    \item[3)] Вычислите:\\
а) \(\sin 930^{\circ}\).
  \end{itemize}
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{16. Формулы приведения}
Вариант 1
\begin{itemize}
  \item[1.] а) $-\sin 56^{\circ}$; 6) $\cos 0,4 \pi$; 2) a) $-\operatorname{ctg} 8^{\circ}$; 3) а) $-\frac{1}{2}$.
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        task = next(item for item in tasks if item.external_id == "sr/16/v1/1")
        by_label = {item.label: item.author_answer_latex for item in task.subitems}
        self.assertIn(r"\sin 56", by_label["1"])
        self.assertIn(r"ctg", by_label["2"])
        self.assertIn(r"frac", by_label["3"])

    def test_ziv_nested_answer_item_stays_on_parent(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{16. Формулы приведения}
Вариант 1
\begin{itemize}
  \item[1.] 1) Приведите:\\
а) \(\sin 304^{\circ}\).
  \begin{itemize}
    \item[2)] Приведите ещё:\\
а) \(\operatorname{tg} 278^{\circ}\).
    \item[3)] Вычислите:\\
а) \(\sin 930^{\circ}\).
  \end{itemize}
  \item[2.] Упростите \(x+x\).
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{16. Формулы приведения}
Вариант 1
\begin{enumerate}
  \item
  \begin{enumerate}
    \item a) \(-\sin 56^{\circ}\); 6) \(\cos 0,4 \pi\); 2) a) \(-\operatorname{ctg} 8^{\circ}\);
  \end{enumerate}
\end{enumerate}
\begin{enumerate}
  \setcounter{enumi}{1}
  \item \(2x\).
\end{enumerate}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        first = by_id["sr/16/v1/1"]
        second = by_id["sr/16/v1/2"]
        glued = " ".join(
            [first.author_answer_latex]
            + [item.author_answer_latex for item in first.subitems])
        self.assertIn(r"\sin 56", glued)
        self.assertNotIn(r"\sin 56", second.author_answer_latex)
        self.assertIn("2x", second.author_answer_latex.replace(" ", ""))

    def test_ziv_glued_decimal_inequality_is_next_task(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{12. Тригонометрия}
Вариант 6
\begin{itemize}
  \item[3.] Упростите \(1+1\).
  \item[4.] При каких \(x\) разность отрицательна?
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{12. Тригонометрия}
Вариант 6
\begin{itemize}
  \item[3.] 1. \(4.0 \leqslant x<\frac{\pi}{6}\).
\end{itemize}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        third = by_id["sr/12/v6/3"].author_answer_latex
        fourth = by_id["sr/12/v6/4"].author_answer_latex
        self.assertIn("1", third)
        self.assertNotIn(r"leqslant", third)
        self.assertIn(r"leqslant", fourth)

    def test_ziv_hint_after_list_keeps_later_answer(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{3. Системы}
Вариант 7
\begin{itemize}
  \item[4.] Первая система.
  \item[5.] Вторая система.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{3. Системы}
Вариант 7
\begin{itemize}
  \item[4.] \((1 ; 0)\).
\end{itemize}
Указание: решите относительно \(x\ldots 5 .(2 ; 3)\).
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertIn("1", by_id["sr/03/v7/4"].author_answer_latex)
        self.assertIn("2", by_id["sr/03/v7/5"].author_answer_latex)
        self.assertNotIn("5 .", by_id["sr/03/v7/4"].author_answer_latex)

    def test_ziv_skips_first_compute_when_answers_start_at_two(self):
        source = r"""
\section*{Самостоятельные работы}
\section*{6. Корень}
Вариант 1
\begin{itemize}
  \item[1.] Вычислите \(\sqrt[3]{8 \cdot 125}\).
  \item[2.] Вынесите множитель \(\sqrt[3]{54 a^{3}}\).
  \item[3.] Внесите множитель \(3 a \sqrt[4]{a}\).
  \item[4.] Область определения.
\end{itemize}
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
\section*{Самостоятельные работы}
\section*{6. Корень}
Вариант 1
\begin{enumerate}
  \item \(3 a \sqrt[3]{2}\).
  \item \(\sqrt[4]{3 a^{6}}\). 4. \(x \neq \pm 2\).
\end{enumerate}
"""
        tasks, _ = parse_ziv(source)
        by_id = {task.external_id: task for task in tasks}
        self.assertFalse((by_id["sr/06/v1/1"].author_answer_latex or "").strip())
        self.assertIn("3 a", by_id["sr/06/v1/2"].author_answer_latex)
        self.assertIn(r"3 a^{6}", by_id["sr/06/v1/3"].author_answer_latex)
        self.assertIn("2", by_id["sr/06/v1/4"].author_answer_latex)

    def test_ziv_broken_speed_units_are_wrapped(self):
        from problems.textbook_parser import apply_imported_answer
        self.assertEqual(apply_imported_answer(r"2$ км/ч$"), r"$2$ км/ч")

    def test_writer_creates_three_review_artifacts(self):
        bundle = ImportBundle(1, "test", {}, [], {
            "tasks_with_subitems": 0,
            "tasks_with_author_answer": 0,
            "tasks_with_author_solution": 0,
            "review_counts": {},
        })
        with tempfile.TemporaryDirectory() as directory:
            write_bundle(bundle, Path(directory))
            self.assertEqual(
                {path.name for path in Path(directory).iterdir()},
                {"import.json", "review.tsv", "report.md"},
            )


if __name__ == "__main__":
    unittest.main()
