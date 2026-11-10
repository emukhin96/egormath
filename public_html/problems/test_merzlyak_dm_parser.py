"""Тесты профиля «ДМ Мерзляка»: фрагменты в духе OCR Mathpix, не идеальный TeX.

Тексты задач — из «Математика. 6 класс. Дидактические материалы»
(текстовый слой PDF), разметка — как у Mathpix: заголовки ``\\section*``,
колонтитулы, списки ``enumerate``, рисунки в ``figure`` или строкой
«Рис. N» рядом с картинкой.
"""

from django.test import SimpleTestCase

from independentworks.analogs import ANALOG_PROFILES, variant_identity

from .forms import TextbookBundleUploadForm
from .merzlyak_dm_parser import (
    detect_book, flatten_lists, group_thousands, parse_merzlyak_dm,
    reorder_column_items, wrap_bare_arithmetic, Figures, extract_figure_tables)
from .textbook_parser import bundle_from_text


TITLE = r"""\documentclass[10pt]{article}
\begin{document}
Мерзляк А.Г.\\
Математика : 6 класс : дидактические материалы : пособие для учащихся

\section*{Содержание}
Упражнения . . . . . 4\\
Вариант 1 . . . . . 4\\
Контрольные работы . . . . . 125
"""

VARIANT = r"""
\section*{Упражнения}
\section*{Вариант {k}}
\section*{Делители и кратные}
1. Какие из чисел 2, 3, 4, 6, 7, 8, 14, 15, 18 являются:\\
1) делителями 28; 3) делителями 24 и 28;\\
2) кратными 3; 4) делителями 36 и кратными 4?\\
2. Запишите все делители числа:\\
1) 6; 2) 17; 3) 44; 4) 60.

\section*{Признаки делимости на 10, на 5 и на 2}
\begin{enumerate}
  \setcounter{enumi}{2}
  \item Из чисел 24, 576, 4 325, 8 211 выпишите те, которые делятся нацело:
  \begin{enumerate}
    \item на 2 ;
    \item на 5 .
  \end{enumerate}
\end{enumerate}

\section*{Вариант {k}}
4
4. На диаграмме (рис. {fig}) изображены объёмы продажи очков.
\section*{Окружность и круг}
5. Укажите центр и радиус окружности.
"""

TESTS = r"""
\section*{Контрольные работы}
\section*{Вариант {k}}
\section*{Контрольная работа № 1}
Тема. Делимость натуральных чисел\\
1. Разложите число 1 056 на простые множители.\\
2. Найдите наибольший общий делитель чисел: 1) 24 и 42; 2) 280 и 588.
\section*{Контрольная работа № 2}
\section*{Тема. Сравнение, сложение и\\
вычитание дробей}
1. Сократите дробь: 1) \(\frac{12}{16}\); 2) \(\frac{18}{27}\).
\end{document}
"""


def figure(number, name):
    return (r"\begin{figure}[h]" "\n" r"\begin{center}" "\n"
            rf"\includegraphics[max width=\textwidth]{{{name}}}" "\n"
            r"\captionsetup{labelformat=empty}" "\n"
            rf"\caption{{Рис. {number}}}" "\n" r"\end{center}" "\n" r"\end{figure}" "\n")


def book_text(variants=4, tests=2):
    parts = [TITLE]
    for k in range(1, variants + 1):
        fig = str(k)
        # Рисунок к задаче 4 OCR поставил над ней — в блок задачи 3.
        chunk = VARIANT.replace("{k}", str(k)).replace("{fig}", fig)
        chunk = chunk.replace("\\section*{Вариант " + str(k) + "}\n4\n",
                              "\\section*{Вариант " + str(k) + "}\n4\n" + figure(fig, f"pic-{k}"), 1)
        parts.append(chunk)
    for k in range(1, tests + 1):
        part = TESTS.replace("{k}", str(k))
        if k < tests:
            part = part.replace(r"\end{document}", "")
        parts.append(part)
    return "".join(parts)


BOOK = {
    "key": "test", "subject": "Математика", "grade": 6, "title": "Тестовая книга",
    "exercises": {"variants": 4, "tasks": 5, "topics": [
        {"first": 1, "title": "Делители и кратные", "topic": "ARI.02.01"},
        {"first": 3, "title": "Признаки делимости на 10, на 5 и на 2", "topic": "ARI.02.01"},
        {"first": 5, "title": "Окружность и круг", "topic": "GEO.04.01"},
    ]},
    "tests": {"variants": 2, "works": [
        {"number": 1, "title": "Делимость натуральных чисел", "tasks": 2, "topic": "ARI.02.01"},
        {"number": 2, "title": "Сравнение, сложение и вычитание дробей", "tasks": 1, "topic": "ARI.03.04",
         "topics": {"1": "ARI.03.02"}},
    ]},
}


class BookStructureTests(SimpleTestCase):
    def setUp(self):
        self.tasks, self.diagnostics = parse_merzlyak_dm(book_text(), book=BOOK)
        self.by_id = {task.external_id: task for task in self.tasks}

    def test_variants_and_tests_with_running_headers(self):
        self.assertEqual(self.diagnostics["tasks_by_variant"],
                         {"В1": 5, "В2": 5, "В3": 5, "В4": 5})
        self.assertEqual(self.diagnostics["missing_task_ids"], [])
        self.assertEqual(self.diagnostics["tests_by_work"],
                         {"КР1.В1": 2, "КР2.В1": 1, "КР1.В2": 2, "КР2.В2": 1})
        self.assertEqual(self.diagnostics["tests_task_count_mismatch"], [])
        self.assertEqual(len(self.tasks), 26)
        self.assertEqual(self.diagnostics["duplicate_task_ids"], [])

    def test_locators_follow_analog_contract(self):
        self.assertIn("merzlyak_dm", ANALOG_PROFILES)
        keys = {variant_identity(7, f"ДМ.В{k}/2")[0] for k in range(1, 5)}
        self.assertEqual(len(keys), 1)
        for k in range(1, 5):
            self.assertIn(f"ДМ.В{k}/5", self.by_id)
        tests = {variant_identity(7, f"КР1.В{k}/2")[0] for k in (1, 2)}
        self.assertEqual(len(tests), 1)
        self.assertEqual(variant_identity(7, "ДМ.В3/170")[:2],
                         ("variants:7:ДМ:all:170", "Упражнения · все варианты · №170"))
        self.assertEqual(variant_identity(7, "КР12.В2/5")[1], "КР 12 · все варианты · №5")
        self.assertIn("КР2.В2/1", self.by_id)
        self.assertEqual(self.by_id["ДМ.В3/4"].source_number, "4")

    def test_paths_topics_and_grade(self):
        task = self.by_id["ДМ.В2/3"]
        self.assertEqual(task.source_path,
                         ["Упражнения", "Признаки делимости на 10, на 5 и на 2", "Вариант 2"])
        self.assertEqual(task.topic_code, "ARI.02.01")
        self.assertEqual(task.collection_title, "Вариант 2")
        self.assertEqual(task.grade_band_codes, ["GRADE_6"])
        # Задача 4 — ещё тема «Признаки делимости»: заголовок темы
        # «Окружность и круг» стоит после неё и в условие не попадает.
        self.assertEqual(self.by_id["ДМ.В1/4"].topic_code, "ARI.02.01")
        self.assertNotIn("Окружность", self.by_id["ДМ.В1/4"].text_latex)
        self.assertEqual(self.by_id["ДМ.В4/5"].topic_code, "GEO.04.01")
        test = self.by_id["КР2.В1/1"]
        self.assertEqual(test.source_path, [
            "Контрольные работы",
            "Контрольная работа № 2. Сравнение, сложение и вычитание дробей",
            "Вариант 1"])
        # Темы по номерам задачи важнее темы работы (итоговая КР).
        self.assertEqual(test.topic_code, "ARI.03.02")
        self.assertEqual(self.by_id["КР1.В2/2"].topic_code, "ARI.02.01")
        self.assertEqual(self.diagnostics["topic_headings_mismatch"], [])

    def test_no_author_answers(self):
        self.assertFalse(any(t.author_answer_latex or t.author_solution_latex
                             for t in self.tasks))

    def test_column_items_sorted_by_label(self):
        task = self.by_id["ДМ.В1/1"]
        self.assertEqual([item.label for item in task.subitems], ["1", "2", "3", "4"])
        self.assertEqual(task.subitems[1].text_latex, "кратными $3$")
        self.assertIn("и кратными $4$?", task.subitems[3].text_latex)
        self.assertIn("ДМ.В1/1", self.diagnostics["column_items"])

    def test_enumerate_numbers_and_nested_items(self):
        task = self.by_id["ДМ.В1/3"]
        self.assertIn("$4\\,325$", task.text_latex)
        self.assertEqual([item.label for item in task.subitems], ["1", "2"])
        self.assertEqual(task.subitems[0].text_latex, "на $2$")

    def test_figure_moves_to_referencing_task(self):
        task = self.by_id["ДМ.В2/4"]
        self.assertEqual(task.images, ["pic-2"])
        self.assertIn(r"\taskpic{1}", task.text_latex)
        self.assertNotIn("рис.", task.text_latex)
        self.assertEqual(self.by_id["ДМ.В2/3"].images, [])
        self.assertEqual(self.diagnostics["figures_unreferenced"], [])
        self.assertEqual(self.diagnostics["figures_numbered"], 4)

    def test_page_number_and_running_header_dropped(self):
        for task in self.tasks:
            self.assertNotIn("Вариант", task.text_latex)
            self.assertNotIn("Упражнения", task.text_latex)
        self.assertFalse(self.by_id["ДМ.В1/3"].subitems[-1].text_latex.rstrip().endswith("4"))

    def test_bundle_and_form_profile(self):
        bundle = bundle_from_text("merzlyak_dm", book_text())
        self.assertEqual(bundle.profile, "merzlyak_dm")
        self.assertEqual(bundle.diagnostics["book"],
                         "Математика. 6 класс. Дидактические материалы")
        self.assertIn("merzlyak_dm", dict(TextbookBundleUploadForm.PROFILE_CHOICES))


class BookDetectionTests(SimpleTestCase):
    def test_known_book_by_title(self):
        book = detect_book("Математика : 6 класс : дидактические материалы\nВариант 1")
        self.assertEqual(book["key"], "mat6")
        self.assertEqual(book["exercises"]["tasks"], 229)

    def test_unknown_book_parses_with_headings_as_topics(self):
        text = book_text().replace("Математика : 6 класс", "Алгебра : 11 класс")
        tasks, diagnostics = parse_merzlyak_dm(text)
        self.assertTrue(diagnostics["book_unknown"])
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["ДМ.В3/4"].source_path[1], "Признаки делимости на 10, на 5 и на 2")
        self.assertEqual(by_id["ДМ.В3/5"].source_path[1], "Окружность и круг")
        self.assertEqual(by_id["ДМ.В3/5"].topic_code, "")
        self.assertEqual(by_id["ДМ.В1/1"].grade_band_codes, ["GRADE_11"])

    def test_text_without_variants_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Не найдены «Упражнения» ДМ Мерзляка"):
            parse_merzlyak_dm(TITLE + "1. Задача без вариантов.\n\\end{document}")

    def test_known_book_counts_mismatch_reported(self):
        # Структура ДМ-6 ждёт 229 задач в варианте — недостающие видны.
        tasks, diagnostics = parse_merzlyak_dm(book_text())
        self.assertIn("ДМ.В1/6", diagnostics["missing_task_ids"])
        self.assertIn("КР1.В1: 2 из 7", diagnostics["tests_task_count_mismatch"])


class FragmentTests(SimpleTestCase):
    def test_reorder_column_items(self):
        body = ("Сравните дроби:\n1) \\(\\frac{9}{10}\\) и \\(\\frac{17}{20}\\); "
                "3) \\(\\frac{3}{10}\\) и \\(\\frac{4}{15}\\);\n"
                "2) \\(\\frac{4}{9}\\) и \\(\\frac{10}{27}\\); 4) \\(\\frac{6}{7}\\) и \\(\\frac{2}{3}\\).")
        text, changed = reorder_column_items(body)
        self.assertTrue(changed)
        self.assertEqual(text.splitlines()[0], "Сравните дроби:")
        self.assertTrue(text.splitlines()[2].startswith("2) \\(\\frac{4}{9}\\)"))
        self.assertTrue(text.splitlines()[4].endswith("\\(\\frac{2}{3}\\)."))

    def test_reorder_keeps_figure_reference_and_ordered_items(self):
        body = "На рисунке (рис. 2) изображены: 1) отрезок; 2) луч."
        self.assertEqual(reorder_column_items(body), (body, False))

    def test_group_thousands(self):
        self.assertEqual(group_thousands("Числа 24, 576, 4 325 и 20 104 050."),
                         "Числа 24, 576, $4\\,325$ и $20\\,104\\,050$.")
        self.assertEqual(group_thousands(r"\(4752\) и \(2 \cdot 3\)"),
                         r"\(4\,752\) и \(2 \cdot 3\)")
        self.assertEqual(group_thousands("0,632 и 1) 18; 3) 126"), "0,632 и 1) 18; 3) 126")

    def test_flatten_lists_with_counter(self):
        text = flatten_lists("\\begin{enumerate}\n\\setcounter{enumi}{9}\n\\item Задача.\n"
                             "\\begin{enumerate}\n\\item пункт\n\\item пункт\n\\end{enumerate}\n"
                             "\\item Следующая.\n\\end{enumerate}")
        self.assertIn("10. Задача.", text)
        self.assertIn("1) пункт", text)
        self.assertIn("2) пункт", text)
        self.assertIn("11. Следующая.", text)

    def test_stray_caption_pairs_with_bare_picture(self):
        text = (TITLE + "\\section*{Вариант 1}\n"
                "1. Укажите центр, радиус и хорду окружности, изображённой на рисунке 1. Рис. 1\n"
                "\\includegraphics[max width=\\textwidth, center]{circle}\n"
                "2. Начертите круг.\n\\end{document}")
        tasks, diagnostics = parse_merzlyak_dm(text, book={"title": "т", "grade": 6})
        self.assertEqual(tasks[0].images, ["circle"])
        self.assertIn("на рисунке \\taskpic{1}", tasks[0].text_latex)
        self.assertNotIn("Рис.", tasks[0].text_latex)
        self.assertEqual(tasks[1].images, [])

    def test_stray_captions_paired_with_pictures_above(self):
        # Обе картинки выше подписей (ниже картинок нет): замена первой
        # не должна сдвинуть вырезание второй подписи.
        text = (TITLE + "\\section*{Вариант 1}\n"
                "\\includegraphics[max width=\\textwidth]{first-picture-long-name}\n"
                "\\includegraphics[max width=\\textwidth]{second-picture-long-name}\n"
                "1. Найдите радиус окружности на рисунке 1. Рис. 1\n"
                "2. Найдите диаметр окружности на рисунке 2. Рис. 2\n"
                "3. Начертите круг.\n\\end{document}")
        tasks, diagnostics = parse_merzlyak_dm(text, book={"title": "т", "grade": 6})
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(diagnostics["figure_captions_without_picture"], [])
        self.assertEqual(by_id["ДМ.В1/1"].images, ["second-picture-long-name"])
        self.assertEqual(by_id["ДМ.В1/2"].images, ["first-picture-long-name"])
        self.assertTrue(by_id["ДМ.В1/2"].text_latex.startswith(
            "Найдите диаметр окружности на рисунке \\taskpic{1}"))
        for task in tasks:
            self.assertNotIn("Рис.", task.text_latex)

    def test_caption_line_below_each_picture(self):
        # Две картинки подряд, у каждой подпись строкой ниже: рисунки не
        # должны поменяться местами.
        text = (TITLE + "\\section*{Вариант 1}\n"
                "1. Сравните отрезки (рис. 5).\n"
                "\\includegraphics[max width=\\textwidth, center]{a}\\\\\n"
                "Рис. 5\n"
                "\\includegraphics[max width=\\textwidth, center]{b}\\\\\n"
                "Рис. 6\n"
                "2. Измерьте угол (рис. 6).\n"
                "\\begin{figure}[h]\n\\includegraphics{c}\n\\end{figure}\n"
                "Рис. 7\n"
                "3. Найдите площадь фигуры на рисунке 7.\n\\end{document}")
        tasks, diagnostics = parse_merzlyak_dm(text, book={"title": "т", "grade": 6})
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["ДМ.В1/1"].images, ["a"])
        self.assertEqual(by_id["ДМ.В1/2"].images, ["b"])
        self.assertEqual(by_id["ДМ.В1/3"].images, ["c"])
        self.assertEqual(diagnostics["figures_unreferenced"], [])
        for task in tasks:
            self.assertNotIn("Рис.", task.text_latex)


class MathpixMarkupTests(SimpleTestCase):
    """Разметка настоящего Mathpix (ДМ 5, алгебра 7–10, 08.11.2026)."""

    def parse(self, body, tests=""):
        text = TITLE + "\\section*{Вариант 1}\n" + body + "\n" + tests + "\n\\end{document}"
        tasks, diagnostics = parse_merzlyak_dm(text, book={"title": "т", "grade": 5})
        return {task.external_id: task for task in tasks}, diagnostics

    def test_figure_table_captions_by_column(self):
        by_id, diagnostics = self.parse(
            "\\begin{itemize}\n  \\item[1.] Найдите \\(R K\\) (рис. 2).\n"
            "  \\item[2.] Найдите \\(M B\\) (рис. 3).\n\n"
            "\\begin{tabular}[t]{|l|l|}\n\\hline\nРис. 2 & Рис. 3 \\\\\n\\hline\n"
            "\\includegraphics[max width=\\textwidth, alt={}]{left}\n"
            " & \\includegraphics[max width=\\textwidth, alt={}]{right}\n \\\\\n\\hline\n"
            "\\end{tabular}\n\\end{itemize}")
        self.assertEqual(by_id["ДМ.В1/1"].images, ["left"])
        self.assertEqual(by_id["ДМ.В1/2"].images, ["right"])
        self.assertNotIn("array", by_id["ДМ.В1/2"].text_latex)
        self.assertEqual(diagnostics["figures_numbered"], 2)

    def test_lost_caption_picture_in_next_block(self):
        by_id, diagnostics = self.parse(
            "\\begin{itemize}\n  \\item[1.] Запишите все углы, изображённые на рисунке 85.\\\\\n"
            "2. Постройте:\n  \\begin{itemize}\n    \\item[1)] угол \\(A P R\\);\n"
            "    \\item[2)] угол \\(B O C\\).\n  \\end{itemize}\n"
            "    \\includegraphics[max width=\\textwidth, alt={}]{angles}\n"
            "  \\item[3.] Решите уравнение.\n\\end{itemize}")
        self.assertEqual(by_id["ДМ.В1/1"].images, ["angles"])
        self.assertEqual(by_id["ДМ.В1/2"].images, [])
        self.assertIn("рис. 85", diagnostics["figures_caption_lost"])

    def test_figure_number_inside_formula(self):
        by_id, _diagnostics = self.parse(
            "1. На рисунке \\(11 \\angle A B C=54^{\\circ}\\), найдите угол.\n"
            + figure("11", "abc") + "2. Следующая.")
        self.assertEqual(by_id["ДМ.В1/1"].images, ["abc"])
        self.assertIn("\\angle A B C", by_id["ДМ.В1/1"].text_latex)

    def test_plain_line_heading_not_glued_to_previous_task(self):
        book = {"title": "т", "grade": 5, "exercises": {"variants": 1, "tasks": 2, "topics": [
            {"first": 1, "title": "Отрезок. Длина отрезка", "topic": "GEO.01.01"},
            {"first": 2, "title": "Прямая. Луч", "topic": "GEO.01.01"}]}}
        text = (TITLE + "\\section*{Вариант 1}\n\\section*{Отрезок. Длина отрезка}\n\\begin{itemize}\n  \\item[1.] Найдите отрезок.\n"
                "\\end{itemize}\n\nПрямая. Луч\n  \\item[2.] Пересекаются ли прямые?\n\\end{document}")
        tasks, diagnostics = parse_merzlyak_dm(text, book=book)
        self.assertEqual(tasks[0].text_latex, "Найдите отрезок.")
        self.assertEqual(diagnostics["topic_headings_mismatch"], [])

    def test_book_end_not_glued_to_last_test_task(self):
        by_id, _diagnostics = self.parse(
            "1. Задача.",
            "\\section*{Вариант 1}\n\\section*{Контрольная работа № 1 \\\\\n Тема. Неравенства}\n"
            "\\begin{itemize}\n  \\item[1.] Докажите неравенство.\n\\end{itemize}\n"
            "\\section*{Справочный материал}\nЧисловые промежутки\n\\section*{Содержание}\nОт авторов ..... 3")
        task = by_id["КР1.В1/1"]
        self.assertEqual(task.text_latex, "Докажите неравенство.")
        self.assertEqual(task.source_path[1], "Контрольная работа № 1. Неравенства")

    def test_bold_digits_named_functions_and_arithmetic(self):
        by_id, _diagnostics = self.parse(
            "1. Вычислите: 28 • 13-4 228: 14.\n"
            "2. Упростите \\(x^{2}+\\frac{1}{x^{2}}=\\mathbf{1 4}\\) и \\(y=\\boldsymbol{\\operatorname { a r c t g }} x\\) на \\(\\boldsymbol{R}\\).\n"
            "3. Найдите аначение выражения:\\\\\n1) 608 • 76;\\\\\n2) 1 и 2.")
        self.assertIn("\\(28 \\cdot 13-4\\,228: 14\\)", by_id["ДМ.В1/1"].text_latex)
        text = by_id["ДМ.В1/2"].text_latex
        self.assertIn("=14", text)
        self.assertIn("\\operatorname{arctg} x", text)
        self.assertIn("\\mathbb{R}", text)
        task = by_id["ДМ.В1/3"]
        self.assertIn("значение", task.text_latex)
        self.assertEqual(task.subitems[0].text_latex, "\\(608 \\cdot 76\\)")
        self.assertEqual(task.subitems[1].text_latex, "$1$ и $2$")

    def test_book_without_title_page_detected_by_preface(self):
        book = detect_book("\\section*{От авторов}\nДанное пособие входит в учебно-методический "
                           "комплект для 10 класса авторов А. Г. Мерзляка, Д. А. Номировского, "
                           "В. Б. Полонского\n\\section*{Вариант 1}")
        self.assertEqual(book["key"], "alg10")
        self.assertEqual(book["exercises"]["variants"], 3)


class QaRulesTests(SimpleTestCase):
    """Правила по вычитке пяти книг агентами (artifacts/merzlyak-dm/qa, 08.11.2026)."""

    def parse(self, body, grade=7, book=None):
        text = TITLE + "\\section*{Вариант 1}\n" + body + "\n\\end{document}"
        tasks, _diagnostics = parse_merzlyak_dm(text, book=book or {"title": "т", "grade": grade})
        return {task.external_id: task for task in tasks}

    def test_ocr_z_label_is_three_and_columns_reordered(self):
        by_id = self.parse("1. Разложите на множители:\\\\\n1) \\(a^{2}+1\\);\\\\\n4) \\(a^{2}+4\\);\\\\\n"
                           "2) \\(a^{2}+2\\);\\\\\n5) \\(a^{2}+5\\);\\\\\nз) \\(a^{2}+3\\);\\\\\n6) \\(a^{2}+6\\).\n2. Дальше.")
        items = by_id["ДМ.В1/1"].subitems
        self.assertEqual([item.label for item in items], ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(items[2].text_latex, "\\(a^{2}+3\\)")

    def test_label_inside_formula(self):
        by_id = self.parse("1. Верно ли:\\\\\n1) \\(8 \\in N\\);\\\\\n\\(2)-5,4 \\in N\\).\n2. Дальше.")
        items = by_id["ДМ.В1/1"].subitems
        self.assertEqual(len(items), 2)
        self.assertIn("\\mathbb{N}", items[1].text_latex)

    def test_enumerate_items_are_subitems_not_tasks(self):
        # Задачи 2 и 3 — enumerate со счётчиком у текущего номера; пункты задачи
        # 2 — список формул без счётчика; пункт 2 задачи 4 — продолжение
        # списка со \setcounter{enumi}{1}.
        by_id = self.parse(
            "\\begin{itemize}\n  \\item[1.] Задача.\n\\end{itemize}\n"
            "\\begin{enumerate}\n  \\setcounter{enumi}{1}\n  \\item Решите уравнение:\n\\end{enumerate}\n"
            "\\begin{enumerate}\n  \\item \\(\\sqrt{x}=1\\);\n  \\item \\(\\sqrt{x}=2\\).\n\\end{enumerate}\n"
            "\\begin{itemize}\n  \\item[3.] Решите уравнение:\\\\\n1) \\(x=1\\);\\\\\n2) \\(x=2\\).\n\\end{itemize}\n"
            "\\begin{itemize}\n  \\item[4.] Сократите дробь:\n  \\begin{itemize}\n    \\item[1)] \\(\\frac{a}{b}\\);\n"
            "  \\end{itemize}\n\\end{itemize}\n"
            "\\begin{enumerate}\n  \\setcounter{enumi}{1}\n  \\item \\(\\frac{c}{d}\\).\n\\end{enumerate}")
        self.assertEqual(sorted(by_id), ["ДМ.В1/1", "ДМ.В1/2", "ДМ.В1/3", "ДМ.В1/4"])
        self.assertEqual(len(by_id["ДМ.В1/2"].subitems), 2)
        self.assertEqual([i.label for i in by_id["ДМ.В1/4"].subitems], ["1", "2"])

    def test_stars_restored_from_italic(self):
        by_id = self.parse("1. В записи чисел вместо нескольких цифр поставили звёздочки. Сравните:\\\\\n"
                           "1) 63 *** и 61 **\\textit{;\\\\\n2) 28} и 1 **\\textit{;\\\\\n3) * \\textit{1} и 99}.\n2. Дальше.",
                           grade=5)
        items = by_id["ДМ.В1/1"].subitems
        self.assertEqual(items[0].text_latex, "\\(63{*}{*}{*}\\) и \\(61{*}{*}{*}\\)")
        self.assertEqual(items[2].text_latex, "\\({*}{*}1{*}\\) и \\(99{*}\\)")

    def test_whole_arithmetic_items_and_quantities(self):
        by_id = self.parse("1. Вычислите:\\\\\n1) 7,3 - 5,8;\\\\\n2) (12 078+1485)+(6922+3515);\\\\\n"
                           "3) 54 м 24 см - 18 м 19 см.\n2. Сравните 3617009 и 3616 356.", grade=5)
        items = by_id["ДМ.В1/1"].subitems
        self.assertEqual(items[0].text_latex, "\\(7{,}3 - 5{,}8\\)")
        self.assertEqual(items[1].text_latex, "\\((12\\,078+1485)+(6922+3515)\\)")
        self.assertIn("$-$", items[2].text_latex)
        self.assertIn("$3\\,617\\,009$ и $3\\,616\\,356$", by_id["ДМ.В1/2"].text_latex)

    def test_units_formula_and_dash_in_grade_five(self):
        by_id = self.parse("1. Выразите в гектарах: \\(340000 м^{2} ; 56 к м^{2}\\).\n"
                           "2. Саша съел \\(-\\frac{5}{10}\\) арбуза.", grade=5)
        self.assertEqual(by_id["ДМ.В1/1"].text_latex,
                         "Выразите в гектарах: $340\\,000$ м$^{2}$; $56$ км$^{2}$.")
        self.assertIn("съел — \\(", by_id["ДМ.В1/2"].text_latex)
        algebra = self.parse("1. Значение равно \\(-\\frac{1}{2}\\).\n2. Дальше.")
        self.assertNotIn("—", algebra["ДМ.В1/1"].text_latex)

    def test_sets_series_estimates_and_intervals(self):
        by_id = self.parse("1. Даны \\(A=\\{2,4\\}\\), ряд \\(1,9,25,49\\), оценка \\(30<a<50,10<b<40\\), "
                           "дробь \\(5,(16)\\) и промежуток [-4; 2).\n2. Дальше.")
        text = by_id["ДМ.В1/1"].text_latex
        for part in ("\\{2, 4\\}", "1, 9, 25, 49", "50, 10<b", "5{,}(16)", "\\([-4; 2)\\)"):
            self.assertIn(part, text)

    def test_common_tail_moves_to_stem(self):
        by_id = self.parse("1. Между какими натуральными числами находится число: 1) 16; 2) 374? "
                           "Ответ запишите в виде двойного неравенства.\n2. Дальше.", grade=5)
        task = by_id["ДМ.В1/1"]
        self.assertTrue(task.text_latex.endswith("Ответ запишите в виде двойного неравенства."))
        self.assertEqual(task.subitems[1].text_latex, "$374$?")
        self.assertIn("Общая фраза перенесена из последнего пункта в условие: проверить", task.warnings)

    def test_ocr_words_and_topic_overrides(self):
        book = {"title": "т", "grade": 8, "exercises": {"variants": 1, "tasks": 2, "numbers": {"2": "ALG.02.04"},
                "topics": [{"first": 1, "title": "Повторение", "topic": "ALG.02.12"}]}}
        by_id = self.parse("1. Пайдите зпачение выражения.\n2. Разложитє на множители.", book=book)
        self.assertEqual(by_id["ДМ.В1/1"].text_latex, "Найдите значение выражения.")
        self.assertEqual(by_id["ДМ.В1/1"].topic_code, "ALG.02.12")
        self.assertEqual(by_id["ДМ.В1/2"].topic_code, "ALG.02.04")
        self.assertIn("Разложите", by_id["ДМ.В1/2"].text_latex)

    def test_figure_table_cell_with_own_caption(self):
        # Строка 2 — «картинка Рис. 2» в одной ячейке: подпись своя, не «Рис. 1» сверху.
        figures = Figures()
        text = ("\\begin{tabular}{c}\nРис. 1 \\\\\n\\includegraphics{pic-one} \\\\\n"
                "\\includegraphics{pic-two} Рис. 2 \\\\\n\\end{tabular}")
        extract_figure_tables(text, figures)
        self.assertEqual(figures.by_number.get("1"), ["pic-one"])
        self.assertEqual(figures.by_number.get("2"), ["pic-two"])

    def test_picture_file_names_untouched(self):
        # «…-8ef57041ca2e-…»: правило разрядов не должно трогать имя файла.
        name = "666e51e3-f294-4e56-ba6d-8ef57041ca2e-027_717_1090_1099_112"
        by_id = self.parse("1. На рисунке 3 изображён график функции.\\\\\n"
                           "\\includegraphics[max width=\\textwidth, alt={}, center]{" + name + "}\n2. Дальше.")
        self.assertEqual(by_id["ДМ.В1/1"].images, [name])
        digits = "666e51e3-f294-4e56-ba6d-12345678-027_717_1090_1099_112"
        by_id = self.parse("1. Рисунок.\\\\\n\\includegraphics[max width=\\textwidth, center]{" + digits + "}\n2. Дальше.")
        self.assertEqual(by_id["ДМ.В1/1"].images, [digits])

    def test_captioned_picture_path_untouched(self):
        # Подписанный рисунок к этому моменту уже \\taskpic{путь}: цифровой
        # сегмент UUID не должен стать «$12\\,345\\,678$».
        name = "666e51e3-f294-4e56-ba6d-12345678-027_717_1090_1099_112"
        body = "На рисунке \\taskpic{merzlyak_dm/" + name + ".jpg} изображено 12 345 точек."
        out = group_thousands(body)
        self.assertIn("\\taskpic{merzlyak_dm/" + name + ".jpg}", out)
        self.assertIn("$12\\,345$", out)

    def test_thousands_after_minus_grouped(self):
        # Дефис перед числом в прозе — минус или диапазон, разряды нужны.
        by_id = self.parse("1. Температура -12 345 градусов.\n2. Цена от 10 000-20 000 рублей.")
        self.assertIn("$-12\\,345$", by_id["ДМ.В1/1"].text_latex)
        second = by_id["ДМ.В1/2"].text_latex
        self.assertIn("10\\,000", second)
        self.assertIn("20\\,000", second)
        self.assertNotIn("$20$", second)

    def test_interval_inside_formula_not_wrapped_again(self):
        # Вложенная \\(…\\(…\\)…\\) роняет сборку LaTeX (Алгебра 10, № 143, 309).
        by_id = self.parse("1. Найдите координаты точки, полученной при повороте точки \\(P_{0}(1; 0)\\) на угол \\(90^{\\circ}\\).\n"
                           "2. Найдите значение \\(f(x)=x^{2}\\) на промежутке [-1; 2] и на (0; + \\(\\infty\\)).")
        self.assertIn("\\(P_{0}(1; 0)\\)", by_id["ДМ.В1/1"].text_latex)
        self.assertIn("\\([-1; 2]\\)", by_id["ДМ.В1/2"].text_latex)
        self.assertIn("\\((0; +\\infty)\\)", by_id["ДМ.В1/2"].text_latex)
        for task in by_id.values():
            self.assertEqual(task.warnings, [])

    def test_decimal_at_inequality_start_kept(self):
        # «1,5<x<3» — десятичная дробь, а не две оценки «1, 5<x».
        by_id = self.parse("1. Решите \\(1,5<x<3\\) и \\(-2,5 \\leqslant x\\).\n"
                           "2. Известно, что \\(30<a<50,10<b<40\\) и \\(tg \\beta=1,5,0<\\alpha\\).")
        first = by_id["ДМ.В1/1"].text_latex
        self.assertNotIn("1, 5", first)
        self.assertNotIn("2, 5", first)
        second = by_id["ДМ.В1/2"].text_latex
        self.assertIn("50, 10<b", second)
        self.assertIn("1,5, 0<", second.replace("{,}", ","))

    def test_items_after_semicolon_in_one_line(self):
        # «; 2) …» в одной строке: метка не должна уйти в формулу.
        by_id = self.parse("1. Вычислите: 1) 7,3 - 5,8; 2) 4,2 + 1,1.\n"
                           "2. Найдите значение: 1) 28 • 13; 2) 608 • 76.")
        for eid in ("ДМ.В1/1", "ДМ.В1/2"):
            task = by_id[eid]
            self.assertEqual([item.label for item in task.subitems], ["1", "2"])
            for item in task.subitems:
                self.assertNotIn(")", item.text_latex.replace("\\)", ""))

    def test_division_colon_not_item_label(self):
        # «:» — деление: «12)» после него не метка пункта.
        out = wrap_bare_arithmetic("Вычислите: 1) (84 : 12) • 5 - 3; 2) 96 : 8.")
        self.assertIn("\\((84 : 12) \\cdot 5 - 3\\)", out)
        self.assertNotIn("•", out)

    def test_explicit_numbers_counted_in_items_list(self):
        # Список «\\item[2.] \\(…\\)» ушёл в режим пунктов, но номера 2, 3
        # учитываются: следующий словесный список идёт с 4, без дублей.
        text = ("\\item[1.] Решите уравнение.\n\\begin{enumerate}\n\\item[2.] \\(2x+1=3\\)\n"
                "\\item[3.] \\(x-1=0\\)\n\\end{enumerate}\n\\begin{enumerate}\n"
                "\\item Найдите значение x.\n\\item Найдите значение y.\n\\end{enumerate}")
        out = flatten_lists(text)
        self.assertIn("4. Найдите значение x.", out)
        self.assertIn("5. Найдите значение y.", out)

    def test_letter_m_in_formula_untouched(self):
        # «2 m» прозой — единица «м», а в формуле m — переменная одночлена.
        by_id = self.parse("1. Упростите \\(5 m n\\), \\(2 m ; 3 n\\) и \\(4 m \\cdot n\\).\n"
                           "2. Длина участка 2 m. Запишите \\(0,(3)\\) и 6,(23).")
        first = by_id["ДМ.В1/1"].text_latex
        self.assertIn("5 m n", first)
        self.assertIn("2 m ; 3 n", first)
        self.assertIn("4 m \\cdot n", first)
        self.assertNotIn("м", first.replace("Упростите", ""))
        second = by_id["ДМ.В1/2"].text_latex
        self.assertIn("$2$ м.", second)
        self.assertNotIn(" m", second)
        self.assertIn("\\(6{,}(23)\\)", second)
        for task in by_id.values():
            self.assertNotIn("Вложенные или незакрытые формулы: сверить с книгой", task.warnings)

    def test_broken_delimiters_warned(self):
        by_id = self.parse("1. Мусор OCR \\(\\min _{\\([5; 7]\\)} f(x)\\).\n2. Дальше.")
        self.assertIn("Вложенные или незакрытые формулы: сверить с книгой", by_id["ДМ.В1/1"].warnings)

    def test_question_of_last_item_stays_in_item(self):
        # «3) Цена 200 р. Найдите новую цену…» — вопрос самого пункта (ревью #336).
        by_id = self.parse("1. Решите задачи: 1) найдите $20$\\% от $50$; 2) сколько процентов $3$ от $12$; "
                           "3) цена товара была $200$ р., а после уценки её снизили на четверть, и ещё раз на "
                           "десятую часть от новой цены. Найдите новую цену после скидки.\n2. Дальше.", grade=5)
        task = by_id["ДМ.В1/1"]
        self.assertIn("Найдите новую цену", task.subitems[2].text_latex)
        self.assertEqual(task.warnings, [])

    def test_carafe_word_untouched(self):
        by_id = self.parse("1. В графин налили $2$ л воды. Сколько воды в графине?\n2. Дальше.", grade=5)
        self.assertIn("В графин налили", by_id["ДМ.В1/1"].text_latex)



class Mat6OcrTests(SimpleTestCase):
    """Классы OCR из TEX Mathpix ДМ-6 (10.11.2026)."""

    def parse(self, body):
        text = TITLE + "\\section*{Вариант 1}\n" + body + "\n\\end{document}"
        tasks, _diagnostics = parse_merzlyak_dm(text, book={"title": "т", "grade": 6})
        return {task.external_id: task for task in tasks}

    def test_escaped_section_heading_not_in_previous_task(self):
        by_id = self.parse("1. Постройте четырёхугольник \\(A B C D\\).\\\\\n"
                           "\\textbackslash section*\\{Параллельные прямые\\}\n2. Начертите прямую \\(m\\).")
        self.assertNotIn("section", by_id["ДМ.В1/1"].text_latex)
        self.assertNotIn("Параллельные", by_id["ДМ.В1/1"].text_latex)

    def test_g_label_among_digits_is_two(self):
        by_id = self.parse("1. Решите уравнение:\\\\\n1) \\(-4 x=32\\);\\\\\nз) \\(-1,2 x=-3,6\\);\\\\\n"
                           "5) \\(x=1\\);\\\\\nг) \\(0,7 x=-1,4\\);\\\\\n4) \\(x=2\\);\\\\\n6) \\(x=3\\).\n2. Дальше.")
        labels = [item.label for item in by_id["ДМ.В1/1"].subitems]
        self.assertEqual(labels, ["1", "2", "3", "4", "5", "6"])
        self.assertIn("0{,}7", by_id["ДМ.В1/1"].subitems[1].text_latex)

    def test_g_label_in_letter_list_untouched(self):
        by_id = self.parse("1. Сравните:\\\\\nа) \\(1\\) и \\(2\\);\\\\\nб) \\(3\\) и \\(4\\);\\\\\n"
                           "в) \\(5\\) и \\(6\\);\\\\\nг) \\(7\\) и \\(8\\).\n2. Дальше.")
        self.assertIn("г)", by_id["ДМ.В1/1"].text_latex + "".join(i.label for i in by_id["ДМ.В1/1"].subitems))
        self.assertNotIn("2)", by_id["ДМ.В1/1"].text_latex)

    def test_g_label_letter_list_after_digit_task(self):
        """Окно — только своя задача: цифры соседней задачи и «; 2)» в координатах не в счёт."""
        long = "очень длинный пункт про точку \\(A(1; 2)\\) и её образ " * 4
        by_id = self.parse("1. Решите:\\\\\n1) \\(x=1\\);\\\\\n3) \\(x=3\\).\n"
                           f"2. Постройте:\\\\\nа) {long};\\\\\nб) {long};\\\\\nв) {long};\\\\\n"
                           "г) \\(B(1; 2)\\).\n3. Дальше.")
        task = by_id["ДМ.В1/2"]
        self.assertIn("г", task.text_latex + "".join(i.label for i in task.subitems))
        self.assertNotIn("2", [i.label for i in task.subitems])

    def test_latin_hod_points_untouched(self):
        by_id = self.parse("1. Найдите \\(\\angle HOD\\), если треугольник HOK равнобедренный.\n"
                           "2. Найдите HOK (16; 24).\n3. Дальше.")
        self.assertIn("HOD", by_id["ДМ.В1/1"].text_latex)
        self.assertIn("HOK", by_id["ДМ.В1/1"].text_latex)
        self.assertIn("НОК", by_id["ДМ.В1/2"].text_latex)

    def test_latin_lookalikes_and_seconds(self):
        by_id = self.parse("1. Найдите HOК \\((12; 18)\\) и HOK \\((16; 24)\\). Какую часть минуты составляют 18 c?\n"
                           "2. Из них 27 \\% собрали ученики 6 «B» класса.")
        first = by_id["ДМ.В1/1"].text_latex
        self.assertIn("НОК", first)
        self.assertNotIn("HOK", first)
        self.assertIn("$18$ с?", first)
        self.assertIn("«В»", by_id["ДМ.В1/2"].text_latex)

    def test_number_split_between_formulas_joined(self):
        by_id = self.parse("1. Какое из чисел больше: 20104 050 или 20 104 500?\n2. Дальше.")
        text = by_id["ДМ.В1/1"].text_latex
        self.assertNotRegex(text, r"\$\s+\$\d{3}\$")

    def test_label_glued_to_minus(self):
        by_id = self.parse("1. Между какими целыми числами лежит число:\\\\\n1) \\(4 \\frac{2}{3}\\);\\\\\n"
                           "2)-6,14;\\\\\n\\(3)-0,7\\);\\\\\n4) -0,6?\\\\\nОтвет запишите в виде двойного неравенства.\n2. Дальше.")
        items = by_id["ДМ.В1/1"].subitems
        self.assertEqual([item.label for item in items], ["1", "2", "3", "4"])
        self.assertNotIn("2)", items[1].text_latex)
        self.assertIn("-6{,}14", items[1].text_latex)

    def test_dash_before_value_is_not_minus_before_negatives(self):
        text = (TITLE + "\\section*{Вариант 1}\n1. Скорость теплохода \\(20\\) км/ч, скорость течения реки "
                "\\(\\displaystyle -1 \\frac{7}{8}\\) км/ч.\n2. Дальше.\n\\end{document}")
        book = {"title": "т", "grade": 6, "exercises": {"negatives_from": 148}}
        tasks, _ = parse_merzlyak_dm(text, book=book)
        first = {t.external_id: t for t in tasks}["ДМ.В1/1"].text_latex
        self.assertIn("реки — ", first)
        self.assertNotIn("-1", first)
        # После темы отрицательных чисел минус остаётся минусом.
        tasks, _ = parse_merzlyak_dm(text, book={"title": "т", "grade": 6})
        self.assertIn("-1", {t.external_id: t for t in tasks}["ДМ.В1/1"].text_latex)

    def test_operator_repeated_on_line_wrap(self):
        by_id = self.parse("1. Упростите выражение \\(5(-1,4 a+3)-(1-2,5 a)-\\) \\(-4(0,8 a+3)\\) и вычислите.\n"
                           "2. Разложите: \\(\\left(a^{12}+\\right.\\) \\(\\left.+1\\right)\\).\n3. Дальше.")
        self.assertIn("-(1-2{,}5 a)-4(0{,}8 a+3)", by_id["ДМ.В1/1"].text_latex)
        self.assertNotIn("+ +", by_id["ДМ.В1/2"].text_latex)
        self.assertIn("a^{12}+1", by_id["ДМ.В1/2"].text_latex)
