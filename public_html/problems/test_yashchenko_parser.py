"""Профиль ``yashchenko_ege``: разбор синтетического TEX в формате Mathpix
сборника «36 вариантов ЕГЭ» (варианты, таблицы ответов, решения части 2)."""
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from . import yashchenko_parser as yp
from .textbook_parser import bundle_from_text

BLANK = "Ответ: \\_\\_\\_\\_."


def variant(number, header=None, tasks=None):
    header = header or f"\\section*{{ВАРИАНТ {number} \\\\\n Часть 1}}"
    body = [header,
            "Ответом к заданиям 1-13 является целое число или конечная десятичная дробь.",
            "", "\\begin{itemize}"]
    tasks = tasks or {}
    for n in range(1, 21):
        body.append(tasks.get(n, f"  \\item[{n}] Найдите число {n}.\\\\\n{BLANK}"
                              if n <= 13 else f"  \\item[{n}] Решите задачу {n}."))
    body.append("\\end{itemize}")
    return "\n".join(body)


def answers(number, rows=None):
    rows = rows or {}
    lines = [f"\\caption{{Вариант {number}}}", "\\begin{tabular}[t]{|l|l|}",
             "\\hline", "№ задания & Ответ \\\\", "\\hline"]
    for n in range(1, 21):
        lines += [f"{n} & {rows.get(n, n)} \\\\", "\\hline"]
    lines += ["\\end{tabular}", "\\end{table}"]
    return "\n".join(lines)


CRITERIA = ("\\begin{center}\n\\begin{tabular}[t]{|l|l|}\n\\hline\n"
            "Содержание критерия & Баллы \\\\\n\\hline\nВерно & 2 \\\\\n\\hline\n"
            "Максимальный балл & 2 \\\\\n\\hline\n\\end{tabular}\n\\end{center}\n")


def book(variants, tables, solutions=""):
    return "\n".join([
        "\\begin{document}", *variants, "\\section*{ОТВЕТЫ}", *tables,
        "\\section*{РЕШЕНИЯ И КРИТЕРИИ ОЦЕНИВАНИЯ ЗАДАНИЙ ЧАСТИ 2}", solutions,
        "\\section*{ЧОУ ДПО «Московский центр»}", "\\end{document}"])


def parse(text):
    with mock.patch.object(yp, "REPAIRS_PATH", Path("/nonexistent")), \
            mock.patch.object(yp, "STRUCTURE_PATH", Path("/nonexistent")), \
            mock.patch.object(yp, "VARIANTS", 2):
        return yp.parse_yashchenko(text)


class YashchenkoParserTests(SimpleTestCase):
    def test_variants_markers_exam_codes_and_topics(self):
        second = variant(2, header="\\section*{ВАРИകΗ 2}\n\\section*{Часть 1}", tasks={
            3: "3 Шар вписан в цилиндр, объём которого равен 180.\\\\\n" + BLANK})
        tasks, diagnostics = parse(book([variant(1), second], [answers(1), answers(2)]))
        self.assertEqual(diagnostics["missing_task_ids"], [])
        self.assertEqual(len(tasks), 40)
        task = {t.external_id: t for t in tasks}["В2/3"]
        self.assertTrue(task.text_latex.startswith("Шар вписан в цилиндр"))
        self.assertNotIn("Ответ", task.text_latex)
        self.assertEqual(task.exam_item_codes, ["EGE_PROFILE_2027_03"])
        self.assertEqual(task.grade_band_codes, ["GRADE_10_11"])
        self.assertEqual(task.collection_title, "Вариант 2")
        self.assertEqual(task.topic_code, "GEO")
        self.assertEqual(task.author_answer_latex, "$3$")

    def test_side_figure_moves_out_of_sentence_and_repeated_lead_dropped(self):
        tasks, _ = parse(book([variant(1, tasks={
            1: ("  \\item[1] Два угла четырёхугольника равны 48°\\\\\n"
                "\\includegraphics[max width=\\textwidth, center]{p-075_1_1_9_9}\\\\\n"
                "Два угла четырёхугольника равны 48° и 74°. Найдите угол.\\\\\n" + BLANK),
            2: ("  \\item[2] Даны векторы.\\\\\n" + BLANK + "\n"
                "\\includegraphics[max width=\\textwidth, center]{p-075_2_2_9_9}\\\\"),
        }), variant(2)], [answers(1), answers(2)]))
        first, third = tasks[0], tasks[2]
        self.assertEqual(first.text_latex,
                         "Два угла четырёхугольника равны $48^{\\circ}$ и $74^{\\circ}$. "
                         "Найдите угол.\n\\taskpic{1}")
        # Рисунок после поля ответа №2 — боковой рисунок №3 (стереометрия).
        self.assertEqual(third.images, ["p-075_2_2_9_9"])
        self.assertEqual(tasks[1].images, [])

    def test_figure_owner_table_overrides_heuristic(self):
        text = book([variant(1, tasks={
            2: ("  \\item[2] На координатной плоскости изображены векторы.\\\\\n" + BLANK
                + "\n\\includegraphics[max width=\\textwidth]{p-071_658_650_1140_1255}"),
        }), variant(2)], [answers(1), answers(2)])
        edition = {"figure_owners": {"p-071_658_650_1140_1255": "В1/2"}}
        with mock.patch.object(yp, "load_edition", return_value=edition):
            tasks, _ = parse(text)
        self.assertEqual(tasks[1].images, ["p-071_658_650_1140_1255"])
        self.assertEqual(tasks[2].images, [])

    def test_subitem_answers_split_and_proof_has_no_answer(self):
        tasks, _ = parse(book([variant(1, tasks={
            15: ("  \\item[15] В пирамиде отмечена точка.\n  \\begin{itemize}\n"
                 "    \\item[а)] Докажите, что точка — середина.\n"
                 "    \\item[б)] Найдите угол.\n  \\end{itemize}"),
            20: ("  \\item[20] Есть камни.\n  \\begin{itemize}\n"
                 "    \\item[a)] Можно ли?\n    \\item[б)] Можно ли иначе?\n"
                 "    \\item[в)] Найдите наименьшее число.\n  \\end{itemize}"),
        }), variant(2)], [answers(1, {
            15: "б) \\(\\frac{2 \\sqrt{21}}{\\sqrt{103}}\\)",
            20: "а) да; б) нет; в) 580 см",
        }), answers(2)]))
        by_id = {t.external_id: t for t in tasks}
        proof, find = by_id["В1/15"].subitems
        self.assertEqual((proof.label, proof.author_answer_latex), ("а", ""))
        self.assertIn("frac", find.author_answer_latex)
        self.assertEqual([(i.label, i.author_answer_latex) for i in by_id["В1/20"].subitems],
                         [("а", "да"), ("б", "нет"), ("в", "$580$ см")])

    def test_answer_series_merged_into_one_formula(self):
        self.assertEqual(
            yp.merge_answer_math(
                "\\(\\pi+2 \\pi n\\), \\(n \\in \\mathbb{Z}\\); "
                "\\( \\frac{\\pi}{2}+2 \\pi l, l \\in \\mathbb{Z} ; \\)"),
            "\\(\\pi+2 \\pi n, n \\in \\mathbb{Z}; \\frac{\\pi}{2}+2 \\pi l, l \\in \\mathbb{Z}\\)")
        self.assertEqual(yp.merge_answer_math("\\(\\frac{\\mathbf{1 6 1}}{\\mathbf{3 0}}\\)"),
                         "\\(\\frac{161}{30}\\)")

    def test_solutions_cut_by_criteria_tables_and_numbered(self):
        solutions = (
            "\\section*{Вариант 1}\n\\begin{itemize}\n  \\item[14] а) Решите уравнение.\\\\\n"
            "Решение.\n Корни \\(x=1\\).\nОтвет: 1.\n\\end{itemize}\n\n" + CRITERIA
            + "\\begin{itemize}\n  \\item[16] Решите неравенство.\\\\\nPeшение.\\\\\n"
              "Ответ: \\((0;1)\\).\n\\end{itemize}\n" + CRITERIA)
        tasks, diagnostics = parse(book([variant(1), variant(2)],
                                        [answers(1), answers(2)], solutions))
        by_id = {t.external_id: t for t in tasks}
        self.assertIn("Корни", by_id["В1/14"].author_solution_latex)
        self.assertNotIn("Решите", by_id["В1/14"].author_solution_latex)
        self.assertNotIn("критерия", by_id["В1/14"].author_solution_latex)
        self.assertEqual(by_id["В1/15"].author_solution_latex, "")
        self.assertIn("Ответ", by_id["В1/16"].author_solution_latex)
        self.assertIn("В1/15: нет решения", diagnostics["solution_warnings"])

    def test_text_fix_requires_unique_fragment(self):
        tasks, _ = parse(book([variant(1), variant(2)], [answers(1), answers(2)]))
        task = tasks[0]
        yp.apply_text_fix(task, {"id": "В1/1", "field": "text",
                                 "before": "число", "after": "значение"})
        self.assertTrue(task.text_latex.startswith("Найдите значение"))
        with self.assertRaises(ValueError):
            yp.apply_text_fix(task, {"id": "В1/1", "field": "text",
                                     "before": "нет такого", "after": "x"})

    def test_profile_is_wired_into_bundle(self):
        with mock.patch.object(yp, "VARIANTS", 2), \
                mock.patch.object(yp, "REPAIRS_PATH", Path("/nonexistent")), \
                mock.patch.object(yp, "STRUCTURE_PATH", Path("/nonexistent")):
            bundle = bundle_from_text(
                "yashchenko_ege", book([variant(1), variant(2)], [answers(1), answers(2)]))
        self.assertEqual(bundle.profile, "yashchenko_ege")
        self.assertEqual(len(bundle.tasks), 40)


class ImportedMathTests(SimpleTestCase):
    def test_table_rules_stay_outside_math(self):
        from .textbook_parser import apply_imported_math
        table = "\\begin{tabular}{|l|l|}\n\\hline\nA & $1$ \\\\\n\\hline\n\\end{tabular}"
        self.assertEqual(apply_imported_math(table), table)

    def test_cyrillic_inside_formula_goes_to_text(self):
        self.assertEqual(
            yp._cyrillic_in_math("\\(R=8{,}31 \\frac{Д ж}{\\text { моль } \\cdot К}\\), \\(T_{п}=15\\)"),
            "\\(R=8{,}31 \\frac{\\text{Дж}}{\\text { моль } \\cdot \\text{К}}\\), \\(T_{\\text{п}}=15\\)")
        self.assertEqual(yp._cyrillic_in_math("\\(v=55 \\mathrm{~км} / \\mathrm{ч}\\)"),
                         "\\(v=55 \\text{км} / \\text{ч}\\)")


class TypographyTests(SimpleTestCase):
    """Замечания владельца 15.11.2026: годы текстом, градусы формулой,
    \\displaystyle, без пустых строк, потерянные точки."""

    def test_years_are_text_and_degrees_are_math(self):
        self.assertEqual(
            yp._years_as_text("В июле $2030$ года; в июле $2031$, $2032$ и $2033$ годов; $2030$ рублей"),
            "В июле 2030 года; в июле 2031, 2032 и 2033 годов; $2030$ рублей")
        self.assertEqual(yp._degrees_in_math("равен 30°. Углы 48° и \\(74^{\\circ}\\)"),
                         "равен $30^{\\circ}$. Углы $48^{\\circ}$ и \\(74^{\\circ}\\)")
        self.assertEqual(yp._degrees_in_math("ниже $21{,}5$ °C"), "ниже $21{,}5^{\\circ}\\mathrm{C}$")

    def test_display_style_for_fractions_and_powers(self):
        self.assertEqual(yp._display_style("\\(m=2^{-\\frac{t}{T}}\\)", exponents=True),
                         "\\(\\displaystyle m=2^{\\textstyle -\\frac{t}{T}}\\)")
        self.assertEqual(yp._display_style("$2^{x^{2}-3}$", exponents=True),
                         "$\\displaystyle 2^{x^{2}-3}$")
        self.assertEqual(yp._display_style("\\(2^{-\\frac{t}{T}}\\)", exponents=False),
                         "\\(\\displaystyle 2^{-\\frac{t}{T}}\\)")
        self.assertEqual(yp._display_style("\\(x^{2}\\)", exponents=True), "\\(x^{2}\\)")

    def test_layout_and_sentence_ends(self):
        self.assertEqual(yp._layout("таковы:\n\n— один;\n\n    — два.\n\nСколько?"),
                         "таковы:\n— один;\n— два.\nСколько?")
        self.assertEqual(yp._sentence_ends("функции \\(f(x)=ax+c\\) Найдите \\(f(1)\\)", close=True),
                         "функции \\(f(x)=ax+c\\). Найдите \\(f(1)\\).")
        self.assertEqual(yp._sentence_ends("если \\(T=14 \\text{ с} ?\\)", close=True),
                         "если \\(T=14 \\text{ с}\\)?")
        self.assertEqual(yp._sentence_ends("Формула\n\\[x=1.\\]", close=True), "Формула\n\\[x=1.\\]")
