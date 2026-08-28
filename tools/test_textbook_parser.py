import tempfile
import unittest
from pathlib import Path

from tools.textbook_parser import (
    Marker,
    ImportBundle,
    bundle_from_text,
    expected_shestakov_ids,
    numeric_markers,
    path_at,
    parse_galitsky,
    parse_shestakov,
    parse_ziv,
    sections,
    shestakov_source_path,
    shestakov_markers,
    split_answer_solution,
    task_from_block,
    write_bundle,
)


class TextbookParserTests(unittest.TestCase):
    def test_explicit_answer_stops_before_solution_after_cleanup(self):
        answer, solution = split_answer_solution(
            "Ответ: 2.\n\nРешение: сложим слагаемые.")
        self.assertEqual(answer, "2.")
        self.assertEqual(solution, "Решение: сложим слагаемые.")

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
            [task.author_answer_latex for task in tasks], ["1.", "2."])
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

    def test_subitem_punctuation_matches_tex_import_rules(self):
        task_text = "\n".join([
            "1.1.A01 Выполните:",
            r"\\ а) Докажите неравенство.",
            r"\\ б) Верно ли обратное?",
            r"\\ в) найдите значение;",
            r"\\ г) $2+2$.",
        ])

        tasks, _ = parse_shestakov(task_text, "")

        self.assertEqual(
            [item.text_latex for item in tasks[0].subitems],
            [
                "Докажите неравенство.",
                "Верно ли обратное?",
                "найдите значение",
                "$2+2$",
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
        self.assertEqual(tasks[0].author_answer_latex, "2.")
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
            [task.author_answer_latex for task in tasks], ["-1.", "4 .", "1."])
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
        self.assertEqual(tasks[0].author_answer_latex, "2.")
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
        self.assertEqual(bundle.tasks[0].author_answer_latex, "2.")
        self.assertEqual(bundle.source, {
            "tasks_file": "book.tex",
            "solutions_file": "solutions.tex",
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
            ["2.", "4."],
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
        self.assertEqual(task.author_solution_latex, "")
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
        self.assertEqual(task.author_solution_latex, "")
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
            ["sr/01/v1/1", "sr/01/v1/2", "sr/01/v2/1", "kr/01/v1/1"],
        )
        self.assertEqual(tasks[0].source_path, [
            "Самостоятельные работы", "Числовые неравенства", "Вариант 1",
        ])
        self.assertEqual(tasks[0].collection_key, "sr/01/v1")
        self.assertEqual(tasks[0].author_answer_latex, r"$\frac{2}{3}<\frac{4}{5}$.")
        self.assertEqual(tasks[2].author_answer_latex, r"$\frac{1}{2}<\frac{2}{3}$.")
        self.assertEqual(tasks[3].author_answer_latex, r"$x>0$.")
        self.assertEqual(diagnostics["matched_solutions"], 4)

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
        self.assertEqual(tasks[0].author_answer_latex, "$1<2$.")
        self.assertEqual(tasks[1].author_answer_latex, "$x>0$.")
        self.assertEqual(diagnostics["matched_solutions"], 2)
        self.assertEqual(diagnostics["duplicate_task_ids"], [])

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
        self.assertEqual(tasks[0].author_answer_latex, "2.")
        self.assertEqual(tasks[1].author_answer_latex, "")
        self.assertFalse(any(
            "Не найден авторский ответ/решение" in warning
            for warning in tasks[1].warnings))

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
