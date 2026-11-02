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
        # Номер рисунка книги из текста убран: рисунок стоит в задаче.
        self.assertIn(r"На рисунке \taskpic{1} показана", self.tasks["1.У1"].text_latex)
        self.assertEqual(self.tasks["1.2"].images, ["bk-017_1_1_1_1"])
        self.assertTrue(self.tasks["1.2"].text_latex.endswith(r"\(A K D\). \taskpic{1}"))
        self.assertIn(r"видна под прямым углом \taskpic{1}.", self.tasks["2.1"].text_latex)
        # Нумерация рисунков начинается заново в каждом параграфе.
        self.assertEqual(self.tasks["2.1"].images, ["bk-020_1_1_1_1"])
        # Колонтитул-подпись «Глава 1. …» — не рисунок задачи.
        self.assertFalse(any("017_2" in path for t in self.tasks.values() for path in t.images))

    def test_figure_refs_keep_part_letters(self):
        tasks, _ = parse_volchkevich(BOOK.replace(
            "углом (рис. 1).", "углом (рис. 1, а, б, в). Найдите угол на рисунке 1."), EDITION)
        task = {t.external_id: t for t in tasks}["2.1"]
        self.assertEqual(task.subitems, [])
        self.assertIn(r"углом \taskpic{1} (рис. а, б, в). Найдите угол на рисунке.", task.text_latex)
        self.assertNotIn("\u2060", task.text_latex)

    def test_repeated_figure_ref_leaves_no_space(self):
        tasks, _ = parse_volchkevich(BOOK.replace(
            "углом (рис. 1).", "углом (рис. 1). Ещё раз взгляните на угол (рис. 1)."), EDITION)
        task = {t.external_id: t for t in tasks}["2.1"]
        self.assertIn("взгляните на угол.", task.text_latex)

    def test_latin_part_letters_by_shape(self):
        tasks, _ = parse_volchkevich(BOOK.replace("углом (рис. 1).", r"углом (рис. \(1, a-e\))."), EDITION)
        task = {t.external_id: t for t in tasks}["2.1"]
        self.assertIn("(рис. а–е)", task.text_latex)

    def test_missing_figure_reported_once(self):
        tasks, diagnostics = parse_volchkevich(BOOK.replace("углом (рис. 1).", "углом (рис. 5)."), EDITION)
        task = {t.external_id: t for t in tasks}["2.1"]
        self.assertEqual(diagnostics["figures_missing_by_task"]["2.1"], ["5"])
        self.assertIn("(рис. 5)", task.text_latex)

    def test_repeated_task_figure_marker_disappears(self):
        tasks, _ = parse_volchkevich(BOOK.replace(
            "Найдите угол \\(A K D\\). ('» рис.)",
            "Найдите угол \\(A K D\\). ('» рис.) Ещё раз (» рис.)."), EDITION)
        task = {t.external_id: t for t in tasks}["1.2"]
        self.assertNotIn("рис.", task.text_latex)
        self.assertNotIn("»", task.text_latex)
        self.assertIn("Ещё раз.", task.text_latex)

    def test_see_figure_with_part_letter_is_not_subitem(self):
        tasks, _ = parse_volchkevich(BOOK.replace("углом (рис. 1).", "углом (см. рис. 1, в)."), EDITION)
        task = {t.external_id: t for t in tasks}["2.1"]
        self.assertEqual(task.subitems, [])
        self.assertIn(r"углом \taskpic{1} (рис. в).", task.text_latex)

    def test_figure_goes_to_subitem_before_solution(self):
        book = BOOK.replace(
            r"Найдите угол \(A K D\). ('» рис.)",
            r"Найдите угол \(A K D\). ('» рис.)").replace(
            "    \\item[б)] разность двух его углов равна 40°.",
            "    \\item[б)] разность двух его углов равна 40° (рис. 31).")
        tasks, _ = parse_volchkevich(book, EDITION)
        task = {t.external_id: t for t in tasks}["1.3"]
        self.assertIn(r"\taskpic{1}", task.subitems[1].text_latex)

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


EDITION_7 = {
    "grade": 7,
    "title": "Тестовое издание 7",
    "chapters": [
        {"number": 2, "title": "Углы и многоугольники", "paragraphs": [
            {"number": 6, "title": "Углы", "anchor": r"\section*{§6 Углы}",
             "topic": "GEO.01.02"},
        ]},
    ],
}

BOOK_7 = r"""
\section*{§6 Углы}
\section*{Аксиомы углов}
\begin{itemize}
  \item[1] Каждый плоский угол имеет определённую градусную меру.
  \item[2] Градусная мера угла равна сумме мер его частей.
\end{itemize}
? ВОПРОСЫ
\begin{itemize}
  \item[1] Что такое геометрический угол?
  \item[2] Какие углы называются смежными?
\end{itemize}
\section*{УПРАЖНЕНИЯ}
\begin{itemize}
  \item[1] Нарисуйте любой треугольник и измерьте его углы транспортиром.
\end{itemize}
\section*{ДАВАЙТЕ РАЗБЕРЁМ НЕСКОЛЬКО ПРИМЕРОВ}
★★★ пример 6.1 Часы показывают 10:30. Найдите угол между стрелками.

РЕШЕНИЕ: Минутная стрелка смотрит на 6, часовая — между 10 и 11.

OTBET: 135°.\\
\section*{РЕШИТЕ ЗАДАЧИ}
\begin{itemize}
  \item[6.1] ★★ Найдите угол между биссектрисами смежных углов.
\end{itemize}
6.2 ★★★ Найдите угол между стрелками часов в 9:30.\\
"""


class VolchkevichGrade7Tests(SimpleTestCase):
    def setUp(self):
        tasks, _ = parse_volchkevich(BOOK_7, EDITION_7)
        self.tasks = {task.external_id: task for task in tasks}

    def test_axioms_and_questions_are_not_exercises(self):
        self.assertEqual(list(self.tasks), ["6.У1", "6.П1", "6.1", "6.2"])
        self.assertIn("транспортиром", self.tasks["6.У1"].text_latex)

    def test_lowercase_example_and_ocr_answer(self):
        self.assertEqual(self.tasks["6.П1"].author_answer_latex, "$135^{\\circ}$")
        self.assertTrue(self.tasks["6.2"].text_latex.startswith("Найдите угол"))


class VolchkevichCanonTests(SimpleTestCase):
    """Канон оформления: docs/TEXTBOOK_PARSE_QA.md, § 5."""

    def test_numbers_units_and_decimal_comma(self):
        from .volchkevich_parser import canon_field
        self.assertEqual(canon_field("Стороны равны 2 и 5, площадь равна 11,25."),
                         "Стороны равны $2$ и $5$, площадь равна $11{,}25$.")
        self.assertEqual(canon_field(r"площадь равна \(2,5 м^{2}\)."), "площадь равна $2{,}5$ м$^{2}$.")
        self.assertEqual(canon_field("периметр 15см"), "периметр $15$ см")
        self.assertEqual(canon_field(r"участка \(0,02 км^{2}\)"), "участка $0{,}02$ км$^{2}$")

    def test_points_lookalikes_and_part_letters(self):
        from .volchkevich_parser import canon_field
        self.assertEqual(canon_field("B четырёхугольнике угол CKD прямой."),
                         "В четырёхугольнике угол $CKD$ прямой.")
        self.assertEqual(canon_field("жил в XIX веке"), "жил в XIX веке")
        self.assertEqual(canon_field(r"на рисунках \taskpic{a.jpg}, \(a-i\)."),
                         r"на рисунках \taskpic{a.jpg} (рис. а–и).")
        self.assertEqual(canon_field("Пусть эта\\\\\nпрямая"), "Пусть эта прямая")

    def test_restructure_and_text_fix(self):
        from .textbook_parser import TaskDraft
        from .volchkevich_parser import apply_text_fix, restructure
        task = TaskDraft(external_id="7.У1", source_number="7.У1", source_path=[],
                         collection_key="", collection_title="", topic_original="",
                         text_latex=r"Найдите $x$ на рисунке \taskpic{p1} \taskpic{p2} (рис. а–б).")
        restructure(task, {"text": "Найдите $x$.", "items": [
            {"label": "а", "pics": [1]}, {"label": "б", "text": "Параллелограмм.", "pics": [2]}]})
        self.assertEqual(task.text_latex, "Найдите $x$.")
        self.assertEqual([(i.label, i.text_latex) for i in task.subitems],
                         [("а", r"\taskpic{p1}"), ("б", r"Параллелограмм. \taskpic{p2}")])
        apply_text_fix(task, {"field": "subitem:б", "old": "Параллелограмм.", "new": "Ромб."})
        self.assertEqual(task.subitems[1].text_latex, r"Ромб. \taskpic{p2}")
        with self.assertRaisesMessage(ValueError, "встречается 0 раз"):
            apply_text_fix(task, {"field": "text_latex", "old": "нет такого", "new": ""})
