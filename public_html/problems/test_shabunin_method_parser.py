"""Тесты профиля методического пособия Шабунина: OCR-фрагменты как в книге."""

from django.test import SimpleTestCase

from .shabunin_method_parser import (
    is_bare_item, parse_shabunin_method, split_example,
    split_trailing_instruction)


STRUCTURE = {
    "grade_bands": ["10"],
    "chapters": [
        {"roman": "II", "title": "Множества и операции над ними",
         "start": "\\section*{Глава II}", "topic": "ALG.02",
         "paragraphs": {"1": "ALG.01.02", "2": "ARI.05.02"}},
    ],
    "end": "\\section*{ПРИМЕРНОЕ ПОУРОЧНОЕ ПЛАНИРОВАНИЕ",
}

BOOK = r"""
\section*{Глава II}
\section*{МНОЖЕСТВА И ОПЕРАЦИИ НАД НИМИ}
Вводный текст главы.

\section*{§1. ОПЕРАЦИИ НАД МНОЖЕСТВАМИ}
Теория параграфа.

Пример 1. Найти \(A \cap B\), если \(A=\{1 ; 2\}, B=\{2 ; 3\}\).\\
△ Общий элемент один. Ответ. \(\{2\}\). \(\square\)

Теория после примера, в импорт не входит.

\section*{Пример 2. Решить неравенство \(\frac{1}{x}>1\).}
\(\Delta\) При \(x>0\) получаем \(x<1\).

Ответ. \((0 ; 1)\). \(\square\)

\section*{§ 2. ЦЕЛЫЕ, РАЦИОНАЛЬНЫЕ И ИРРАЦИОНАЛЬНЫЕ ЧИСЛА}
Пример 1. Доказать, что \(\sqrt{2} \notin \mathbb{Q}\).\\
△ От противного. \(\square\)

\section*{ДИДАКТИЧЕСКИЕ МАТЕРИАЛЫ \\
 Самостоятельная работа II. 1}
Вариант 1\\
Даны множества \(A\) и \(B\).

\begin{itemize}
  \item[1.] Показать множества на диаграммах.
  \item[2.] Выяснить, верно ли включение \(A \subset B\).
\end{itemize}

\section*{Вариант 2*}
Даны множества \(C\) и \(D\).

\begin{itemize}
  \item[1.] Показать множества на диаграммах.
  \item[2.] Выяснить, верно ли равенство \(C=D\).
\end{itemize}

\section*{Ответы}
Вариант 1. 1. См. рис. 1, 2. 2. Верно.\\
Вариант 2. 1. См. рис. 3. 2. Неверно.

\section*{Контрольная работа II. 1 по теме «Множества» (2 урока)}
\section*{Вариант 1}
Решить уравнения:

\begin{enumerate}
  \item \(x^{2}=4\).
  \item \(|x|=3\).
\end{enumerate}

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{book-073_327_298_1633_227}
\captionsetup{labelformat=empty}
\caption{Рис. 1}
\end{center}
\end{figure}

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{book-073_334_301_1627_614}
\captionsetup{labelformat=empty}
\caption{Рис. 2}
\end{center}
\end{figure}

\begin{itemize}
  \item[3.] Найти количество трехзначных чисел, кратных 3.\\
Решить уравнение:
\end{itemize}

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{book-074_326_299_345_224}
\captionsetup{labelformat=empty}
\caption{Рис. 3}
\end{center}
\end{figure}

\begin{itemize}
  \item[4.] \(\sqrt{x}=2\).
\end{itemize}

\section*{Вариант 2}
Решить уравнения:

\begin{enumerate}
  \item \(x^{2}=9\).
  \item \(|x|=5\).
  \item Найти количество трехзначных чисел, кратных 7.
  \item \(\sqrt{x}=3\).
\end{enumerate}

\section*{Ответы}
Вариант 1.

\begin{enumerate}
  \item \(\pm 2\).
  \item \(\pm 3\).
  \item 300.
  \item 4.\\
Вариант 2.
  \item \(\pm 3\).
  \item \(\pm 5\).
  \item 128.
  \item 9.
\end{enumerate}

\section*{Разбор варианта № 1}
\begin{itemize}
  \item[1.] Корни \(x= \pm 2\).
Ответ. \(\pm 2\).
  \item[2.] Модуль равен 3 при \(x= \pm 3\).
\end{itemize}

\section*{ПРИМЕРНОЕ ПОУРОЧНОЕ ПЛАНИРОВАНИЕ УЧЕБНОГО МАТЕРИАЛА}
"""


class ShabuninMethodParserTests(SimpleTestCase):
    def setUp(self):
        tasks, self.diagnostics = parse_shabunin_method(BOOK, structure=STRUCTURE)
        self.tasks = {task.external_id: task for task in tasks}

    def test_examples_by_paragraph(self):
        self.assertEqual(
            [key for key in self.tasks if ".П" in key],
            ["II.1.П1", "II.1.П2", "II.2.П1"])
        first = self.tasks["II.1.П1"]
        self.assertTrue(first.text_latex.startswith("Найти"))
        self.assertIn("Общий элемент один", first.author_solution_latex)
        self.assertNotIn("Теория после примера", first.author_solution_latex)
        self.assertNotIn("\\square", first.author_solution_latex)
        self.assertEqual(first.author_answer_latex, "\\(\\{2\\}\\)")
        self.assertEqual(first.source_path[-1], "§1. Операции над множествами")
        self.assertEqual(first.topic_code, "ALG.01.02")
        self.assertIn("пример с решением", first.tags)

    def test_example_in_heading_and_delta_start(self):
        task = self.tasks["II.1.П2"]
        self.assertFalse(task.text_latex.rstrip().endswith("}"))
        self.assertTrue(task.author_solution_latex.startswith("При"))
        self.assertEqual(task.author_answer_latex, "\\((0 ; 1)\\)")

    def test_variants_stars_and_common_stem(self):
        task = self.tasks["СРII.1.В2/2"]
        self.assertEqual(task.stars, 1)
        self.assertEqual(self.tasks["СРII.1.В1/2"].stars, 0)
        self.assertIn("Даны множества \\(C\\)", task.text_latex)
        self.assertIn("верно ли равенство", task.text_latex)
        self.assertEqual(task.author_answer_latex, "Неверно.")
        self.assertEqual(self.tasks["СРII.1.В1/2"].author_answer_latex, "Верно.")

    def test_answer_figures_by_caption(self):
        answer = self.tasks["СРII.1.В1/1"].author_answer_latex
        self.assertEqual(answer.count("\\taskpic"), 2)
        self.assertEqual(self.tasks["СРII.1.В1/1"].images,
                         ["book-073_327_298_1633_227", "book-073_334_301_1627_614"])
        self.assertEqual(self.tasks["СРII.1.В2/1"].images, ["book-074_326_299_345_224"])
        self.assertNotIn("\\taskpic", self.tasks["КРII.1.В1/3"].text_latex)
        self.assertEqual(self.diagnostics["unused_answer_figures"], {})

    def test_instruction_only_for_bare_items(self):
        self.assertTrue(self.tasks["КРII.1.В1/1"].text_latex.startswith("Решить уравнения:"))
        third = self.tasks["КРII.1.В1/3"]
        self.assertTrue(third.text_latex.startswith("Найти количество"))
        self.assertNotIn("Решить уравнение:", third.text_latex)
        # Формулировка в конце пункта 3 относится к пункту 4.
        self.assertTrue(self.tasks["КРII.1.В1/4"].text_latex.startswith("Решить уравнение:"))
        self.assertTrue(self.tasks["КРII.1.В2/4"].text_latex.startswith("Решить уравнения:"))

    def test_answers_reset_numbering_per_variant(self):
        self.assertEqual(self.tasks["КРII.1.В1/4"].author_answer_latex, "$4$")
        self.assertEqual(self.tasks["КРII.1.В2/1"].author_answer_latex, "\\(\\pm 3\\)")
        self.assertEqual(self.tasks["КРII.1.В2/3"].author_answer_latex, "$128$")
        self.assertEqual(self.tasks["КРII.1.В2/4"].author_answer_latex, "$9$")

    def test_review_of_first_variant(self):
        self.assertIn("Корни", self.tasks["КРII.1.В1/1"].author_solution_latex)
        self.assertNotIn("Модуль", self.tasks["КРII.1.В1/1"].author_solution_latex)
        self.assertIn("Модуль", self.tasks["КРII.1.В1/2"].author_solution_latex)
        self.assertEqual(self.tasks["КРII.1.В2/1"].author_solution_latex, "")

    def test_paths_and_topics(self):
        task = self.tasks["КРII.1.В2/2"]
        self.assertEqual(task.source_path, [
            "Глава II. Множества и операции над ними", "Дидактические материалы",
            "Контрольная работа II.1", "Вариант 2"])
        self.assertEqual(task.topic_original, "Множества")
        self.assertEqual(task.grade_band_codes, ["10"])


class HelpersTests(SimpleTestCase):
    def test_split_example_without_end_mark(self):
        text, solution, answer, warnings = split_example("Найти \\(x\\).\n△ Решение. Ответ: 5.")
        self.assertEqual(text, "Найти \\(x\\).")
        self.assertEqual(answer, "5.")
        self.assertEqual(warnings, ["Не найден знак конца решения □"])

    def test_bare_item(self):
        self.assertTrue(is_bare_item("а) \\(y=x^{2}\\);\\\\\nб) \\(y=|x|\\)."))
        self.assertFalse(is_bare_item("На рисунке изображен график \\(y=f(x)\\)."))

    def test_trailing_instruction_before_picture(self):
        raw = "д) \\(y=f(x)\\).\\\\\nПостроить графики следующих функций:\n\\includegraphics{a}"
        head, line = split_trailing_instruction(raw)
        self.assertEqual(line, "Построить графики следующих функций:")
        self.assertNotIn("Построить", head)
        self.assertIn("\\includegraphics{a}", head)
