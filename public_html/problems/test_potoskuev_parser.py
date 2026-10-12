"""Тесты профиля Потоскуева: OCR-фрагменты как в книге, а не идеальный TeX."""

from django.test import SimpleTestCase

from .potoskuev_parser import (
    parse_potoskuev, renumber_appendix_lists, split_numbered_parts,
    tabular_to_array)


FIGURE = r"""
\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{%s}
\captionsetup{labelformat=empty}
\caption{Рис. %s}
\end{center}
\end{figure}
"""

BOOK = r"""
\section*{Задачи к § 3-4. Аксиомы и следствия из них}
1.001. Укажите среди перечисленных фигур плоские и неплоские фигуры: а) треугольник; б) ромб; в) окружность; г) параллелепипед; д) куб; е) пирамида; ж) сфера; з) ломаная \(A B C E H\); и) фигура, состоящая из рёбер \(P A, P B\) и \(P C\).\\
1.002. :-) Вершина \(B\) параллелограмма \(A B C D\) принадлежит плоскости \(\alpha\) (рис. 1). Верно ли выполнен рисунок?\\
1.003. Дан правильный тетраэдр \(E F G S\). 1) Постройте: а) точку \(Y_{1}\); б) точку \(Y_{2}\). 2) Найдите: а) длину отрезка \(Y_{1} Y_{2}\); б) отношение, в котором плоскость делит отрезок \(S E\).\\
1.004 \({ }^{1}\). Прямая \(a\) лежит в плоскости \(\alpha\). Доказать, что прямая \(b\) также лежит в плоскости \(\alpha\).

Решение. Так как прямые \(a\) и \(b\) параллельны, то через них можно провести плоскость. Значит, \(b \subset \alpha\).
""" + FIGURE % ("uuid-009_1", "1") + r"""
\footnotetext{\({ }^{1}\) Творческая задача.
}
\section*{Графическая работа № 1 :}
Тема: «Следствия из аксиом стереометрии»\\
Сделайте чертежи по условиям задач, используя данные в них обозначения.

\begin{itemize}
  \item[1.] Прямая \(M P\) лежит в плоскости \(\alpha\).
  \item[2.] Прямая \(A B\) пересекает плоскость \(\alpha\) в точке \(M\).
\end{itemize}

\section*{ОТВЕТЫ И УКАЗАНИЯ}
\section*{Глава 1. Введение в стереометрию}
1.002. Указание. Рассмотрите случаи: а) \(А В\) - диаметр окружности; б) \(A B\) - хорда. 1.003.1) а) 6; б) 15; 2) а) 1; б) 1 : 3.

\section*{ОГЛАВЛЕНИЕ}
"""


class PotoskuevParserTests(SimpleTestCase):
    def setUp(self):
        tasks, self.diagnostics = parse_potoskuev(BOOK)
        self.tasks = {task.external_id: task for task in tasks}

    def test_task_numbers_signs_and_footnote_marks(self):
        self.assertEqual(
            list(self.tasks), ["1.001", "1.002", "1.003", "1.004", "ГР1"])
        self.assertTrue(self.tasks["1.002"].text_latex.startswith("Вершина"))

    def test_late_letter_label_is_subitem(self):
        labels = [item.label for item in self.tasks["1.001"].subitems]
        self.assertEqual(labels[-2:], ["з", "и"])

    def test_figure_by_caption(self):
        task = self.tasks["1.002"]
        self.assertEqual(task.images, ["uuid-009_1"])
        self.assertIn(r"\taskpic{1}", task.text_latex)

    def test_numbered_parts_and_their_answers(self):
        task = self.tasks["1.003"]
        self.assertTrue(task.text_latex.startswith("Дан правильный тетраэдр"))
        self.assertEqual([item.label for item in task.subitems], ["1", "2"])
        self.assertIn("а) точку", task.subitems[0].text_latex)
        self.assertIn("\nб) точку", task.subitems[0].text_latex)
        self.assertEqual(task.subitems[0].author_answer_latex, "а) $6$; б) $15$")
        self.assertEqual(task.subitems[1].author_answer_latex, "а) $1$; б) $1 : 3$")
        self.assertEqual(task.author_answer_latex, "")

    def test_worked_example_solution_leaves_condition(self):
        task = self.tasks["1.004"]
        self.assertNotIn("Решение", task.text_latex)
        self.assertTrue(task.author_solution_latex.startswith("Решение."))

    def test_hint_with_cases_stays_whole(self):
        task = self.tasks["1.002"]
        self.assertEqual(task.author_answer_latex, "")
        self.assertIn("а) \\(A B\\)", task.author_solution_latex)
        self.assertIn("б) \\(A B\\) — хорда", task.author_solution_latex)

    def test_graphic_work_is_one_task(self):
        work = self.tasks["ГР1"]
        self.assertTrue(work.text_latex.startswith("Сделайте чертежи"))
        self.assertEqual([item.label for item in work.subitems], ["1", "2"])
        self.assertEqual(work.topic_code, "GEO.08.01")

    def test_path_and_topic(self):
        task = self.tasks["1.001"]
        self.assertEqual(task.source_path, [
            "Глава 1. Введение в стереометрию",
            "Задачи к § 3–4. Аксиомы и следствия из них"])
        self.assertEqual(task.collection_title, "Глава 1. Введение в стереометрию")
        self.assertEqual(task.topic_code, "GEO.08.01")


class PotoskuevHelpersTests(SimpleTestCase):
    def test_appendix_counters_become_task_numbers(self):
        text = renumber_appendix_lists(
            "\\begin{enumerate}\n  \\setcounter{enumi}{112}\n"
            "  \\item Медианы равны 2 и 3.\n  \\item Катеты равны 9 и 12.\n"
            "\\end{enumerate}\n")
        self.assertIn("\n113. Медианы", text)
        self.assertIn("\n114. Катеты", text)

    def test_table_cells_mix_math_and_words(self):
        value = tabular_to_array(
            "\\begin{tabular}{|l|l|}\n\\hline\n1 & \\(L N\\) и \\(E G\\) \\\\\n"
            "\\hline\n2 & TN и EG \\\\\n\\hline\n\\end{tabular}")
        self.assertIn(r"L N \text{и} E G", value)
        self.assertIn(r"TN \text{и} EG", value)
        self.assertNotIn(r"\)", value)

    def test_numbered_parts_need_chain_from_one(self):
        stem, parts = split_numbered_parts(
            "Найдите \\(f(2)\\) при \\(x \\in(1; 2)\\). 2) лишнее")
        self.assertEqual(parts, [])


class PotoskuevOcrRulesTests(SimpleTestCase):
    def parse(self, tasks, answers=""):
        book = ("\\section*{Задачи к § 3-4. Аксиомы и следствия из них}\n" + tasks
                + "\n\\section*{ОТВЕТЫ И УКАЗАНИЯ}\n" + answers
                + "\n\\section*{ОГЛАВЛЕНИЕ}\n")
        tasks, _diagnostics = parse_potoskuev(book)
        return {task.external_id: task for task in tasks}

    def test_six_inside_coordinates_is_not_label(self):
        tasks = self.parse(
            "1.001. Запишите координаты вектора \\(\\vec{b}=\\vec{i}-4 \\vec{j}+6 \\vec{k}\\).\\\\\n"
            "1.002. Найдите точку \\(P\\).\\\\\n",
            "1.001. \\(\\vec{b}(1 ;-4 ; 6)\\). 1.002. (8; 1; 6).")
        self.assertIn("(1 ;-4 ; 6)", tasks["1.001"].author_answer_latex)
        self.assertIn("6)", tasks["1.002"].author_answer_latex)
        self.assertNotIn("б)", tasks["1.002"].author_answer_latex)

    def test_six_label_on_top_level_of_formula_splits_items(self):
        tasks = self.parse(
            "1.001. Составьте уравнение плоскости, проходящей через точки: а) "
            "\\(P(2 ; 0 ; 0), K(0 ; 2 ; 0) ; 6) P(2 ;-1 ; 2)\\), \\(K(1 ;-2 ; 3)\\).\\\\\n")
        labels = [item.label for item in tasks["1.001"].subitems]
        self.assertEqual(labels, ["а", "б"])

    def test_common_tail_of_last_item_goes_to_condition(self):
        task = self.parse(
            "1.001. Опустите перпендикуляры из точки \\(E\\) на прямые: "
            "а) \\(A P\\); б) \\(A C\\). Найдите длину каждого перпендикуляра, "
            "если ребро тетраэдра равно \\(a\\).\\\\\n")["1.001"]
        self.assertTrue(task.text_latex.endswith("равно \\(a\\)."))
        self.assertEqual(task.subitems[-1].text_latex, "\\(A C\\)")

    def test_example_takes_first_answer_only(self):
        task = self.parse(
            "1.001. Найти площадь.\n\nРешение. Первый способ.\nОтвет: \\(2 \\sqrt{5}\\).\\\\\n"
            "Второй способ. Иначе.\nОтвет: \\(2 \\sqrt{5}\\).\\\\\n")["1.001"]
        self.assertEqual(task.author_answer_latex, "\\(2 \\sqrt{5}\\)")
        self.assertIn("Второй способ", task.author_solution_latex)


class PotoskuevPdfSafetyTests(SimpleTestCase):
    def test_tag_moves_out_of_aligned(self):
        from .potoskuev_parser import prepare_text
        value = prepare_text(
            "\\[\n\\begin{aligned}\nx & =1 \\\\\n& =2 \\tag{*}\n\\end{aligned}\n\\]")
        self.assertIn("\\end{aligned} \\tag{*}", value)


class PotoskuevBarePointsTests(SimpleTestCase):
    def test_coordinates_in_condition_become_math(self):
        from .potoskuev_parser import _wrap_bare_points
        self.assertEqual(
            _wrap_bare_points("с центром в точке (2; -3; 4) и M(1; 3; 8), \\(x\\) (рис. 5)"),
            "с центром в точке \\((2; -3; 4)\\) и \\(M(1; 3; 8)\\), \\(x\\) (рис. 5)")


class PotoskuevSignTests(SimpleTestCase):
    def test_letter_o_is_sign_only_before_capital(self):
        from .potoskuev_parser import _clean_task_body
        self.assertEqual(_clean_task_body(" О Величина угла равна 60°."), "Величина угла равна 60°.")
        self.assertEqual(_clean_task_body(" О прямых \\(a\\) и \\(b\\) известно, что они параллельны."),
                         "О прямых \\(a\\) и \\(b\\) известно, что они параллельны.")
        self.assertEqual(_clean_task_body(" (Устно.) О прямых \\(a\\) известно."),
                         "(Устно.) О прямых \\(a\\) известно.")


class PotoskuevMarkerGapTests(SimpleTestCase):
    def test_long_ocr_gap_is_bridged_by_following_numbers(self):
        from .potoskuev_parser import task_markers
        text = ("2.001. Первая.\n2.002. Вторая.\n2.010. Десятая.\n"
                "2.011. Одиннадцатая.\n2.012. Двенадцатая.\n")
        ids = [m.external_id for m in task_markers(text, 2)]
        self.assertEqual(ids, ["2.001", "2.002", "2.010", "2.011", "2.012"])

    def test_far_reference_without_followers_is_not_a_task(self):
        from .potoskuev_parser import task_markers
        text = "2.001. См. ответ 2.040. и рисунок.\n2.002. Вторая.\n2.003. Третья.\n"
        ids = [m.external_id for m in task_markers(text, 2)]
        self.assertEqual(ids, ["2.001", "2.002", "2.003"])

    def test_missing_tail_of_chapter_is_reported(self):
        tasks, diagnostics = parse_potoskuev(BOOK)
        missing = [n for n in diagnostics["missing_task_ids"] if n.startswith("1.")]
        self.assertIn("1.071", missing)


class PotoskuevNewtonTests(SimpleTestCase):
    def test_newtons_leave_formula_for_cyrillic_and_latin_ocr(self):
        for unit in ("Н", "H"):
            book = ("\\section*{Задачи к § 3-4. Аксиомы и следствия из них}\n"
                    "1.001. Каждая из сил равна \\(2 " + unit + "\\). Найдите равнодействующую.\\\\\n"
                    "\\section*{ОТВЕТЫ И УКАЗАНИЯ}\n1.001. \\(3 " + unit + "\\).\n"
                    "\\section*{ОГЛАВЛЕНИЕ}\n")
            task = parse_potoskuev(book)[0][0]
            self.assertIn("\\(2\\) Н.", task.text_latex)
            self.assertEqual(task.author_answer_latex, "$3$ Н")


class PotoskuevChapterZoneTests(SimpleTestCase):
    def test_damaged_first_number_still_opens_chapter(self):
        from .potoskuev_parser import chapter_zones
        text = "1.001. Первая.\n1.002. Вторая.\n2,001. Искажённый номер.\n2.002. Вторая главы 2.\n"
        zones = dict(chapter_zones(text, [1, 2]))
        self.assertNotIn("2.002", zones[1])
        self.assertTrue(zones[2].startswith("2.002."))

    def test_chapter_without_any_number_is_reported(self):
        tasks, diagnostics = parse_potoskuev(BOOK)
        self.assertIn(2, diagnostics["chapters_without_zone"])
        self.assertIn("2.001", diagnostics["missing_task_ids"])
        self.assertIn("2.055", diagnostics["missing_task_ids"])
