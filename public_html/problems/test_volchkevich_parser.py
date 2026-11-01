"""Тесты профиля Волчкевича: OCR-фрагменты как в книге, а не идеальный TeX."""

from django.test import SimpleTestCase

from .volchkevich_parser import cut_at_list_end, number_enumerates, parse_volchkevich


def figure(path: str, caption: str) -> str:
    return r"""
\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{%s}
\captionsetup{labelformat=empty}
\caption{%s}
\end{center}
\end{figure}
""" % (path, caption)


EDITION = {
    "grade": 8,
    "title": "Тестовое издание",
    "chapters": [
        {"number": 1, "title": "Четырёхугольники", "paragraphs": [
            {"number": 1, "title": "Параллелограмм",
             "anchor": r"\section*{Параллелограмм}", "topic": "GEO.03.01"},
            {"number": 2, "title": "Дополнительные построения", "page": 20,
             "topic": "GEO.03.01"},
        ]},
    ],
}

BOOK = r"""
\section*{Параллелограмм}
Теория параграфа.
\section*{УПРАЖНЕНИЯ}
\begin{itemize}
  \item[1.] На рисунке 14 показана штурманская линейка. Объясните, как она устроена.
  \item[2.] Нарисуйте две окружности и найдите на них точки так, чтобы отрезки нахо-
\end{itemize}

\begin{itemize}
  \item[] дились внутри полосы.
\end{itemize}
Возможно, вы уже заметили, что первый признак и первое свойство взаимно обратны.
""" + figure("bk-010_1_1_1_1", "Рис. 14") + r"""
\begin{enumerate}
  \setcounter{enumi}{2}
  \item Докажите четвёртый признак параллелограмма.
\end{enumerate}
Ещё немного теории.
\begin{itemize}
  \item[1.] Верно ли, что диагональ разбивает параллелограмм на два равных треугольника?
  \item[2.] Каким свойством обладают противоположные стороны параллелограмма?
\end{itemize}
§1. Параллелограмм

ПРИМЕР 1. ★★ Две стороны четырёхугольника параллельны (рис. 31). Является ли он параллелограммом?

\section*{РЕШЕНИЕ}
Пусть стороны \(A B\) и \(C D\) параллельны. Значит, он параллелограмм.

OmBem: является.

Дальше снова идёт теория параграфа, а не решение примера.
""" + figure("bk-015_1_1_1_1", "Рис. 31") + r"""
\begin{itemize}
  \item[1.] ★★★ Пара параллельных прямых пересекает три другие. Сколько образовалось параллелограммов?
  \item[2.] ★☆☆ На стороне \(B C\) взяли точку \(K\). Найдите угол \(A K D\). ('» рис.)
  \item[3.] ★★ Найдите углы параллелограмма, если:
  \begin{itemize}
    \item[а)] сумма двух его углов равна 100°;
    \item[б)] разность двух его углов равна 40°.
  \end{itemize}
\end{itemize}
""" + figure("bk-017_1_1_1_1", "» задача 2") + figure("bk-017_2_2_2_2", "Глава 1. Четырёхугольники") + r"""
\section*{Дополнительные построения}
""" + figure("bk-020_1_1_1_1", "Рис. 1") + r"""
\section*{ЗАДАЧИ}
\begin{itemize}
  \item[1.] ★★ Из середины стороны параллелограмма противоположная сторона видна под прямым углом (рис. 1).
\end{itemize}
"""


class VolchkevichParserTests(SimpleTestCase):
    def setUp(self):
        tasks, self.diagnostics = parse_volchkevich(BOOK, EDITION)
        self.tasks = {task.external_id: task for task in tasks}

    def test_kinds_and_numbering(self):
        self.assertEqual(
            list(self.tasks),
            ["1.У1", "1.У2", "1.У3", "1.П1", "1.1", "1.2", "1.3", "2.1"])
        self.assertEqual(self.tasks["1.У1"].source_path,
                         ["Глава 1. Четырёхугольники", "§ 1. Параллелограмм", "Упражнения"])
        self.assertEqual(self.tasks["1.1"].source_path[-1], "Задачи")
        self.assertEqual(self.tasks["2.1"].source_path[1], "§ 2. Дополнительные построения")
        self.assertEqual(self.tasks["1.1"].topic_code, "GEO.03.01")

    def test_questions_without_heading_are_skipped(self):
        # «Вопросы» с нумерацией с 1 не попадают ни в упражнения, ни в текст.
        self.assertNotIn("диагональ разбивает", self.tasks["1.У3"].text_latex)
        self.assertEqual(self.diagnostics["missing_task_ids"], [])

    def test_exercise_stops_at_list_end_but_keeps_page_continuation(self):
        self.assertIn("находились внутри полосы", self.tasks["1.У2"].text_latex.replace("\n", ""))
        self.assertNotIn("Возможно", self.tasks["1.У2"].text_latex)
        self.assertEqual(self.tasks["1.У3"].text_latex,
                         "Докажите четвёртый признак параллелограмма.")

    def test_example_solution_answer_and_theory_tail(self):
        example = self.tasks["1.П1"]
        self.assertTrue(example.text_latex.startswith("Две стороны"))
        self.assertEqual(example.source_path[-1], "Примеры решения задач")
        self.assertEqual(example.author_answer_latex, "является")
        self.assertNotIn("Дальше снова", example.author_solution_latex)
        self.assertEqual(example.stars, 0)

    def test_stars_and_hollow_star_garbage_are_removed(self):
        self.assertTrue(self.tasks["1.1"].text_latex.startswith("Пара"))
        self.assertTrue(self.tasks["1.2"].text_latex.startswith("На стороне"))
        self.assertNotIn("★", self.tasks["1.3"].text_latex)
        self.assertEqual([item.label for item in self.tasks["1.3"].subitems], ["а", "б"])

    def test_figures_by_caption_and_task_caption(self):
        self.assertEqual(self.tasks["1.У1"].images, ["bk-010_1_1_1_1"])
        self.assertIn(r"\taskpic{1}", self.tasks["1.У1"].text_latex)
        self.assertEqual(self.tasks["1.2"].images, ["bk-017_1_1_1_1"])
        self.assertIn(r"(рис.) \taskpic{1}", self.tasks["1.2"].text_latex)
        # Нумерация рисунков начинается заново в каждом параграфе.
        self.assertEqual(self.tasks["2.1"].images, ["bk-020_1_1_1_1"])
        # Колонтитул-подпись «Глава 1. …» — не рисунок задачи.
        self.assertFalse(any("017_2" in path for t in self.tasks.values() for path in t.images))

    def test_running_header_is_not_text(self):
        self.assertNotIn("§1", self.tasks["1.П1"].text_latex)

    def test_unknown_edition_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Неизвестное издание"):
            parse_volchkevich(BOOK)


class VolchkevichHelpersTests(SimpleTestCase):
    def test_number_enumerates_only_with_counter(self):
        text = (r"\begin{enumerate}" "\n" r"\setcounter{enumi}{4}" "\n"
                r"\item Пятое." "\n" r"\item Шестое." "\n" r"\end{enumerate}"
                "\n" r"\begin{enumerate}" "\n" r"\item Шаг решения." "\n" r"\end{enumerate}")
        result = number_enumerates(text)
        self.assertIn(r"\item[5.] Пятое.", result)
        self.assertIn(r"\item[6.] Шестое.", result)
        self.assertIn(r"\item Шаг решения.", result)

    def test_cut_at_list_end(self):
        self.assertEqual(cut_at_list_end(" Условие.\n\\end{itemize}\nТеория."), " Условие.")
        self.assertIn("продолжение", cut_at_list_end(
            " Условие на-\n\\end{itemize}\nпродолжение строки."))
