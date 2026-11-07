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
    reorder_column_items)
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
        text = book_text().replace("Математика : 6 класс", "Алгебра : 7 класс")
        tasks, diagnostics = parse_merzlyak_dm(text)
        self.assertTrue(diagnostics["book_unknown"])
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["ДМ.В3/4"].source_path[1], "Признаки делимости на 10, на 5 и на 2")
        self.assertEqual(by_id["ДМ.В3/5"].source_path[1], "Окружность и круг")
        self.assertEqual(by_id["ДМ.В3/5"].topic_code, "")
        self.assertEqual(by_id["ДМ.В1/1"].grade_band_codes, ["GRADE_7"])

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
