"""Тесты профиля Смирнова: OCR-фрагменты как в книге, а не идеальный TeX."""

import hashlib
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .smirnov_parser import (
    answer_latex, answer_mask, condition_text, list_items, parse_smirnov,
    prose_dashes, tex_answer_chain)


STRUCTURE = {
    "grade_bands": ["GRADE_10_11"],
    "answers_start": r"\section*{Ответы}",
    "level_titles": {"A": "Уровень А", "B": "Уровень В", "C": "Уровень С"},
    "round_bodies_topic": "GEO.10.04",
    "round_bodies_re": "цилиндр|конус|шар|сфер",
    "combination_topic": "GEO.10.05",
    "combination_re": "вписан|описан",
    "sections": [
        {"number": 1, "title": "1. Расстояние между двумя точками в пространстве",
         "topic": "GEO.08.04", "counts": {"": 2}},
        {"number": 5, "title": "5. Угол между прямыми в пространстве",
         "topic": "GEO.08.04", "counts": {"A": 5, "C": 1}},
        {"number": 8, "title": "8. Объем фигур в пространстве",
         "topic": "GEO.09.06", "round_bodies": True, "counts": {"A": 3}},
    ],
}

PIC = r"\includegraphics[max width=\textwidth, alt={}, center]{3dc27f51-3d0d-4d29-bdde-b119b7eef05a-%s}"

BOOK = r"""
\section*{ГЕОМЕТРИЯ }
СТЕРЕОМЕТРИЯ
\section*{1. Расстояние между двумя точками в пространстве}
В этом параграфе рассмотрены задачи на нахождение длин отрезков.

\section*{Задачи}
\begin{enumerate}
  \item Найдите диагональ куба, все ребра которого равны \(\sqrt{3}\).\\
""" + PIC % "007_344_400_585_426" + r"""
  \item Основанием прямой четырехугольной призмы является ромб с острым углом 60° Боковое ребро равно 1 , а большая диагональ - 2. Найдите сторону основания призмы.\\
""" + PIC % "009_403_471_846_392" + r"""
\end{enumerate}

\section*{5. Угол между прямыми в пространстве}
\section*{Общие сведения}
Определение 3. Две прямые называются перпендикулярными, если угол между ними равен 90°
\includegraphics[max width=\textwidth, alt={}, center]{3dc27f51-3d0d-4d29-bdde-b119b7eef05a-111_392_467_262_393}

\section*{Задачи}
\section*{Уровень А}
\begin{enumerate}
  \item В кубе \(A \ldots D_{1}\) найдите угол между прямыми \(A B\) и \(C C_{1}\).\\
""" + PIC % "112_403_468_387_392" + r"""
  \item В кубе \(A \ldots D_{1}\) найдите угол между прямыми \(A B\) и \(B_{1} C_{1}\).\\
""" + PIC % "112_403_469_891_392" + r"""
\end{enumerate}

\begin{itemize}
  \item[3.] В правильном тетраэдре \(A B C D\) точки \(E\) и \(F\) - середины ребер соответственно \(B D\) и \(C D\). Найдите угол между прямыми \(A B\) и \(E F\).
""" + PIC % "113_403_468_322_395" + r"""
  \item[4.] В кубе \(A \ldots D_{1}\) найдите угол между прямыми \(A B\) и \(D C_{1}\).\\
""" + PIC % "113_403_469_826_397" + r"""
\end{itemize}

\begin{enumerate}
  \setcounter{enumi}{4}
  \item В кубе \(A \ldots D_{1}\) найдите угол между прямыми \(A B\) и \(C D_{1}\).\\
""" + PIC % "114_403_469_322_389" + r"""
\end{enumerate}

\section*{Уровень С}
\begin{enumerate}
  \item В кубе \(A \ldots D_{1}\) найдите косинус угла между прямыми \(A B\) и \(C A_{1}\).\\
""" + PIC % "140_403_469_322_389" + r"""
\end{enumerate}

\section*{8. Объем фигур в пространстве}
\section*{Общие сведения}
\section*{Объем пирамиды}
Объем пирамиды равен трети произведения площади основания на высоту.
\section*{Задачи}
\section*{Уровень А}
\begin{enumerate}
  \item Найдите объем цилиндра, площадь основания которого равна 1, а образующая равна 6 и наклонена к плоскости основания под углом 30°\\
""" + PIC % "221_378_421_313_415" + r"""
  \item В параллелепипеде две грани имеют площади 4 и 6 , их общее ребро равно 2. Найдите объем параллелепипеда.\\
""" + PIC % "221_384_292_863_483" + r"""
  \item В куб с ребром 3 вписан шар. Найдите объем этого шара, деленный на \(\pi\).\\
""" + PIC % "236_384_292_863_483" + r"""
\end{enumerate}

\section*{Ответы}
\begin{enumerate}
  \item Расстояние между двумя точками в пространстве
  \item
  \begin{enumerate}
    \item 3. 2. 1.
  \end{enumerate}
\end{enumerate}

\section*{Уровень А}
\[
\begin{aligned}
& \text { 1. 90. 2. 90. 3. 60. 4. 60. 5. } 45 .
\end{aligned}
\]

\section*{Уровень C}
\[
\begin{aligned}
& \text { 1. } \frac{\sqrt{3}}{3} \text {. }
\end{aligned}
\]

\section*{8. Объем фигур в пространстве}
\section*{Уровень А}
\[
\begin{aligned}
& \text { 1. 3. 2. 12. 3. } 4,5 .
\end{aligned}
\]
"""


def answers_for(text, sections):
    return {
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "pdf_sha256": "x",
        "sections": sections,
    }


ANSWERS = {
    "1": {"": {"1": "3", "2": "1"}},
    "5": {"A": {"1": "90", "2": "90", "3": "60", "4": "60", "5": "45"},
          "C": {"1": "\\(\\frac{\\sqrt{3}}{3}\\)"}},
    "8": {"A": {"1": "3", "2": "12", "3": "4{,}5"}},
}


class SmirnovParserTests(SimpleTestCase):
    def parse(self, text=BOOK, answers=ANSWERS, repairs=None):
        with tempfile.TemporaryDirectory() as tmp:
            answers_path = Path(tmp) / "answers.json"
            repairs_path = Path(tmp) / "repairs.json"
            if answers is not None:
                answers_path.write_text(json.dumps(answers_for(text, answers)), encoding="utf-8")
            if repairs is not None:
                repairs_path.write_text(json.dumps(repairs), encoding="utf-8")
            return parse_smirnov(text, structure=STRUCTURE, repairs_path=repairs_path,
                                 answers_path=answers_path)

    def test_numbers_from_enumerate_counter_and_itemize_labels(self):
        tasks, diagnostics = self.parse()
        self.assertEqual(
            [t.external_id for t in tasks],
            ["S1/1", "S1/2", "S5/A1", "S5/A2", "S5/A3", "S5/A4", "S5/A5", "S5/C1", "S8/A1", "S8/A2", "S8/A3"])
        self.assertEqual(diagnostics["count_mismatch"], [])
        self.assertEqual(diagnostics["duplicate_task_ids"], [])

    def test_theory_figures_not_tasks_and_every_task_has_its_picture(self):
        tasks, diagnostics = self.parse()
        self.assertTrue(all(len(t.images) == 1 for t in tasks))
        self.assertNotIn("111_392_467_262_393", " ".join(i for t in tasks for i in t.images))
        self.assertTrue(all(t.text_latex.endswith("\\taskpic{1}") for t in tasks))
        self.assertEqual(diagnostics["pages"]["S5/A3"], 113)

    def test_collections_and_topics(self):
        tasks, _ = self.parse()
        by_id = {t.external_id: t for t in tasks}
        self.assertEqual(by_id["S1/1"].source_path, ["1. Расстояние между двумя точками в пространстве"])
        self.assertEqual(by_id["S5/C1"].source_path, ["5. Угол между прямыми в пространстве", "Уровень С"])
        self.assertEqual(by_id["S5/C1"].collection_title, "Уровень С")
        self.assertEqual(by_id["S5/A1"].topic_code, "GEO.08.04")
        self.assertEqual(by_id["S8/A1"].topic_code, "GEO.10.04")  # цилиндр
        self.assertEqual(by_id["S8/A2"].topic_code, "GEO.09.06")
        self.assertEqual(by_id["S8/A3"].topic_code, "GEO.10.05")  # шар, вписанный в куб
        self.assertEqual(by_id["S8/A3"].answer_mask, "{{decimal: 4,5}}")
        self.assertEqual(by_id["S8/A2"].stars, 0)

    def test_condition_canon(self):
        tasks, diagnostics = self.parse()
        by_id = {t.external_id: t for t in tasks}
        text = by_id["S1/2"].text_latex
        self.assertIn("углом \\(60^{\\circ}\\). Боковое", text)
        self.assertIn("большая диагональ — $2$", text)
        self.assertIn("равно $1$, а", text)
        self.assertNotIn("\\\\", text)
        self.assertIn("\\(E\\) и \\(F\\) — середины", by_id["S5/A3"].text_latex)
        self.assertIn("под углом \\(30^{\\circ}\\).\n\\taskpic{1}", by_id["S8/A1"].text_latex)
        self.assertIn("S8/A1", diagnostics["periods_added"])

    def test_answers_from_table_and_masks(self):
        tasks, diagnostics = self.parse()
        by_id = {t.external_id: t for t in tasks}
        self.assertEqual(by_id["S5/A3"].author_answer_latex, "\\(60\\)")
        self.assertEqual(by_id["S5/A3"].answer_mask, "{{decimal: 60}}")
        self.assertEqual(by_id["S5/C1"].answer_mask, "{{number: \\frac{\\sqrt{3}}{3}}}")
        self.assertEqual(diagnostics["missing_answers"], [])
        self.assertEqual(diagnostics["masks_missing"], [])

    def test_tex_answers_checked_where_readable(self):
        _, diagnostics = self.parse()
        self.assertEqual(diagnostics["answers_tex_checked"], 8)  # 5А, 8А; одиночный ответ 5С не цепочка
        self.assertEqual(diagnostics["answers_tex_mismatch"], [])
        wrong = json.loads(json.dumps(ANSWERS))
        wrong["8"]["A"]["2"] = "13"
        _, diagnostics = self.parse(answers=wrong)
        self.assertEqual(len(diagnostics["answers_tex_mismatch"]), 1)
        self.assertIn("S8/A2", diagnostics["answers_tex_mismatch"][0])

    def test_answers_table_bound_to_source_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "answers.json"
            path.write_text(json.dumps(answers_for("другой TEX", ANSWERS)), encoding="utf-8")
            tasks, diagnostics = parse_smirnov(BOOK, structure=STRUCTURE,
                                               repairs_path=Path(tmp) / "none.json",
                                               answers_path=path)
        self.assertFalse(diagnostics["answers_table"])
        self.assertEqual(len(diagnostics["missing_answers"]), len(tasks))

    def test_repairs_patches_fixes_and_masks(self):
        digest = hashlib.sha256(BOOK.encode("utf-8")).hexdigest()
        repairs = {"editions": [{
            "source_sha256": digest,
            "patches": [{"id": "p1", "page": 9, "before": "ромб с острым углом",
                         "after": "ромб со стороной 1 и острым углом"}],
            "fixes": [{"id": "f1", "page": 112, "task": "S5/A1", "field": "text",
                       "old": "\\(C C_{1}\\)", "new": "\\(C_{1} C\\)"}],
            "answer_masks": {"S5/C1": "{{number: \\frac{1}{\\sqrt{3}}}}"},
        }]}
        tasks, diagnostics = self.parse(repairs=repairs)
        by_id = {t.external_id: t for t in tasks}
        self.assertIn("ромб со стороной $1$ и острым", by_id["S1/2"].text_latex)
        self.assertIn("\\(C_{1} C\\)", by_id["S5/A1"].text_latex)
        self.assertEqual(by_id["S5/C1"].answer_mask, "{{number: \\frac{1}{\\sqrt{3}}}}")
        self.assertEqual(diagnostics["source_repairs_applied"], ["p1"])
        self.assertEqual(diagnostics["fixes_applied"], ["f1"])

    def test_not_smirnov(self):
        with self.assertRaises(ValueError):
            parse_smirnov("\\section*{1. Глава}", structure=STRUCTURE)


class SmirnovHelpersTests(SimpleTestCase):
    def test_list_items_counter_and_labels(self):
        zone = ("\\begin{enumerate}\n  \\item Первая.\n  \\item Вторая.\n\\end{enumerate}\n"
                "\\begin{itemize}\n  \\item[3.] Третья.\n\\end{itemize}\n"
                "\\begin{enumerate}\n  \\setcounter{enumi}{3}\n  \\item Четвёртая.\n\\end{enumerate}")
        self.assertEqual([n for n, _ in list_items(zone)], [1, 2, 3, 4])
        self.assertEqual(list_items(zone)[2][1].split("\n")[0], "Третья.")

    def test_dashes_only_in_prose(self):
        self.assertEqual(prose_dashes("точки \\(E\\) - середина \\(a - b\\)"),
                         "точки \\(E\\) — середина \\(a - b\\)")

    def test_condition_period_before_picture(self):
        text, added = condition_text("Найдите угол \\(30^{\\circ}\\)\n\\taskpic{1}")
        self.assertEqual(text, "Найдите угол \\(30^{\\circ}\\).\n\\taskpic{1}")
        self.assertTrue(added)
        text, added = condition_text("Чему равен объем?\n\\taskpic{1}")
        self.assertFalse(added)

    def test_answer_latex(self):
        self.assertEqual(answer_latex("2,5."), "\\(2,5\\)")
        self.assertEqual(answer_latex("60°"), "\\(60^{\\circ}\\)")
        self.assertEqual(answer_latex("\\(\\frac{\\sqrt{3}}{2}\\)"), "\\(\\frac{\\sqrt{3}}{2}\\)")

    def test_masks_by_printed_answer(self):
        self.assertEqual(answer_mask("$2{,}5$"), "{{decimal: 2,5}}")
        self.assertEqual(answer_mask("$-0{,}6$"), "{{decimal: -0,6}}")
        self.assertEqual(answer_mask("\\(60^{\\circ}\\)"), "{{number: 60}}°")
        self.assertEqual(answer_mask("\\(8 \\pi\\)"), "{{number: 8 \\pi}}")
        self.assertEqual(answer_mask("\\(\\arccos \\frac{1}{3}\\)"), "{{number: \\arccos \\frac{1}{3}}}")
        self.assertEqual(answer_mask("\\(\\operatorname{arctg} 2\\)"), "{{number: \\operatorname{arctg} 2}}")
        # Буква, перечень или текст — ответ разбирает редактор.
        self.assertEqual(answer_mask("\\(\\frac{a \\sqrt{2}}{2}\\)"), "")
        self.assertEqual(answer_mask("\\(1; 2\\)"), "")
        self.assertEqual(answer_mask("\\(2\\) и \\(3\\)"), "")

    def test_tex_answer_chain_aligned_and_array(self):
        zone = (r"\[\begin{aligned}& \text { 1. 48. 2. 8. 3. } \frac{\sqrt{2}}{2} \text {. 4. 4,5. }"
                r"\end{aligned}\]")
        self.assertEqual(tex_answer_chain(zone),
                         {1: "48", 2: "8", 3: "\\frac{\\sqrt{2}}{2}", 4: "4,5"})
        # «2. 3. 3. 54.» — ответ 2 равен 3; ячейки array «3.8 .» — «3. 8.».
        zone = r"\begin{array}{lrr}\text { 1. } 2 . & 2 . & 3 . & 3.8 . & 4.54 .\end{array}"
        self.assertEqual(tex_answer_chain(zone), {1: "2", 2: "3", 3: "8", 4: "54"})
        # Поток списка: «2,5. 10. 1. 11. 2.» — номера 10 и 11, ответы 1 и 2.
        self.assertEqual(tex_answer_chain(r"\item 2,5. 10. 1. 11. 2."), {10: "1", 11: "2"})
