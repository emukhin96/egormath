"""Тесты профиля Ткачук: OCR-фрагменты как в книге, а не идеальный TeX."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .textbook_parser import TaskDraft
from .tkachuk_parser import (
    Item, apply_composition, apply_override, faculty_codes, flatten_answer_stream, heal_ocr,
    homework_tasks, item_number, load_repairs, match_answer_blocks,
    parse_tkachuk, split_answer_hint, split_stream, split_worked,
    variant_answer_blocks, with_stem, year_sections, Repairs)


STRUCTURE = {
    "grade_bands": ["GRADE_10_11"],
    "part2_title": "Подготовка к экзамену",
    "lesson_tasks_title": "Задачи урока",
    "homework_title": "Домашнее задание",
    "part3_title": "Варианты вступительных экзаменов в МГУ",
    "chapters": [
        {"number": 1, "title": "Тригонометрия", "lessons": [
            {"number": 1, "title": "Сведение к квадратным уравнениям", "page": 99,
             "topic": "ALG.03.10"},
            {"number": 2, "title": "Группировка", "page": 109, "level": 2,
             "topic": "ALG.03.10"},
        ]},
    ],
}

BOOK = r"""
\title{МАТЕМАТИКА - АБИТУРИЕНТУ \\ Все о вступительных экзаменах в вузы }
\section*{Ткачук В. В.}
\section*{Часть II}
\section*{Глава 1}
\section*{Тригонометрия}
\section*{Урок 1}
\section*{Сведение к квадратным уравнениям}
Теория урока.

\begin{itemize}
  \item Задача 1. \(4-\cos ^{2} x=4 \sin x\).
\end{itemize}

Решение. Подставим \(1-\sin ^{2} x\).

Ответ: \(x=\frac{\pi}{2}+2 \pi n, n \in \mathbf{Z}\).

\begin{itemize}
  \item[-] Задача 2 [2]. \(\cos ^{4} x=\cos 2 x\).\\
Peшение. Понизим степень.
Ответ: \(x=n \pi, n \in \mathbf{Z}\).
\end{itemize}

Наш первый урок успешно завершен. Оценка.

\section*{Домашнее задание}
\begin{itemize}
  \item[-] 1. \(1+\cos \frac{x}{2}+\cos x=0\)
  \item[] -2. \(2 \sin ^{2} x+\cos 4 x=0\)
  \item[З.] \(\cos x=\frac{1}{2}\)
\end{itemize}

Урок 2

\section*{Группировка}
\begin{itemize}
  \item Задача 1. Решить уравнение \(\sin x=0\).
\end{itemize}

Решение. Просто.

Ответ: \(x=n \pi\).

\section*{Домашнее задание}
\begin{itemize}
  \item[-] 1. Доказать, что \(\sin 2 x=2 \sin x \cos x\).
\end{itemize}

\section*{Часть III}
\section*{1970 год}
\section*{Механико-математический факультет}
\begin{itemize}
  \item[-] 1. Решить неравенство
\[
\log _{2}(1+\cos 4 x) \leqslant 1 .
\]
  \item[-] 2. Найти все действительные решения системы.
\end{itemize}

\section*{Геологический факультет \\
 (отделение геофизики)}
Вариант был такой же, как на химическом факультете этого года.

\section*{Химический факультет}
\begin{itemize}
  \item[-] 1. Решить уравнение \(x=1\).
\end{itemize}

\section*{Ответы, указания, решения}
\section*{1. Домашние задания}
\begin{itemize}
  \item[-] YPOK 1. 1. \(\pi+2 n \pi, n \in \mathbf{Z} .2\). \(2 n \pi, n \in\) Z. Привести уравнение к виду \(\sin x=0\). 3. \(\pm \frac{\pi}{3}+2 n \pi\).
  \item[-] УPOK 2. 1. Записать \(\sin 2 x\) через синус и косинус.
\end{itemize}

\section*{2. Ответы к вариантам за 1970-2021 годы}
1970 год\\
Механико-математический факультет. 1. \(\frac{\pi}{6} \leqslant x .\mathbf{2} . x=\sqrt{6}\).\\
Химический ф-т и отд. геофизики геологического ф-та. 1. 8 час 45 мин.

\section*{Список использованной литературы}
"""


def parse(book=BOOK, repairs=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "repairs.json"
        if repairs is not None:
            import json
            path.write_text(json.dumps(repairs, ensure_ascii=False), encoding="utf-8")
        return parse_tkachuk(book, structure=STRUCTURE, repairs_path=path)


class TkachukBookTests(SimpleTestCase):
    def test_lessons_worked_tasks_and_homework(self):
        tasks, diagnostics = parse()
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(
            list(by_id),
            ["У1.1", "У1.2", "Д1.1", "Д1.2", "Д1.3", "У2.1", "Д2.1",
             "1970.ММ.1", "1970.ММ.2", "1970.ХФ.1"])
        first = by_id["У1.1"]
        self.assertEqual(first.text_latex, r"Решите уравнение \(4-\cos ^{2} x=4 \sin x\).")
        self.assertIn("Подставим", first.author_solution_latex)
        self.assertEqual(first.author_answer_latex, r"\(x=\frac{\pi}{2}+2 \pi n, n \in \mathbf{Z}\)")
        self.assertEqual(first.source_path, [
            "Подготовка к экзамену", "Глава 1. Тригонометрия",
            "Урок 1. Сведение к квадратным уравнениям", "Задачи урока"])
        # Латинское «Peшение» и уровень [2] — в номере источника.
        second = by_id["У1.2"]
        self.assertIn("Понизим", second.author_solution_latex)
        self.assertEqual(second.source_number, "У1.2 [2]")
        # «Наш урок … завершен» — не часть решения.
        self.assertNotIn("завершен", second.author_solution_latex)
        self.assertEqual(diagnostics["structure_problems"], [])

    def test_homework_answers_split_and_hint(self):
        tasks, _ = parse()
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["Д1.1"].author_answer_latex, r"\(\pi+2 n \pi, n \in \mathbf{Z}\)")
        self.assertIn(r"2 n \pi", by_id["Д1.2"].author_answer_latex)
        self.assertEqual(by_id["Д1.2"].author_solution_latex,
                         r"Привести уравнение к виду \(\sin x=0\).")
        # OCR «\item[З.]» — номер 3.
        self.assertIn(r"\pm \frac{\pi}{3}", by_id["Д1.3"].author_answer_latex)
        # Доказательство: в разделе ответов — решение, ответа нет.
        self.assertEqual(by_id["Д2.1"].author_answer_latex, "")
        self.assertIn("Записать", by_id["Д2.1"].author_solution_latex)
        self.assertEqual(by_id["Д2.1"].source_number, "Д2.1 [2]")

    def test_variants_and_their_answers(self):
        tasks, diagnostics = parse()
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["1970.ММ.1"].source_path, [
            "Варианты вступительных экзаменов в МГУ", "1970 год",
            "Механико-математический факультет"])
        self.assertIn(r"\frac{\pi}{6}", by_id["1970.ММ.1"].author_answer_latex)
        self.assertIn(r"\sqrt{6}", by_id["1970.ММ.2"].author_answer_latex)
        self.assertIn("8", by_id["1970.ХФ.1"].author_answer_latex)
        self.assertTrue(any("геофизики" in note for note in diagnostics["sections_without_tasks"]))

    def test_repairs_bound_to_sha_and_composition(self):
        import hashlib
        digest = hashlib.sha256(BOOK.encode("utf-8")).hexdigest()
        repairs = {"editions": [{
            "source_sha256": digest,
            "tasks": {"Д1.1": {"answer": r"\(\pi+2 \pi n\)"}},
            "drop": ["1970.ММ.2"],
            "insert": [{"id": "Д1.4", "after": "Д1.3", "text": r"Решите уравнение \(x=0\).",
                        "answer": r"\(0\)", "solution": ""}],
        }]}
        tasks, diagnostics = parse(repairs=repairs)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(by_id["Д1.1"].author_answer_latex, r"\(\pi+2 \pi n\)")
        self.assertNotIn("1970.ММ.2", by_id)
        self.assertEqual(by_id["Д1.4"].source_path, by_id["Д1.3"].source_path)
        self.assertEqual(diagnostics["inserted"], ["Д1.4"])
        # Чужой скан: правки не применяются.
        repairs["editions"][0]["source_sha256"] = "0" * 64
        tasks, _ = parse(repairs=repairs)
        self.assertIn("1970.ММ.2", {task.external_id for task in tasks})


class TkachukPiecesTests(SimpleTestCase):
    def test_answer_stream_numbers_inside_formulas(self):
        stream = (r"1. \(\pi+2 n \pi, n \in \mathbf{Z} .2\). \(2 n \pi\). 3. \(\frac{\pi}{4}, "
                  r"n \in \mathbf{Z} .4 . \frac{\pi}{2}\). \mathbf{5} . \(0\)")
        pieces, missing = split_stream(stream, 5)
        self.assertEqual(missing, [])
        self.assertEqual(pieces[1], r"\(\pi+2 n \pi, n \in \mathbf{Z}\)")
        self.assertEqual(pieces[4], r"\( \frac{\pi}{2}\).")

    def test_numbers_that_are_answers_do_not_break_chain(self):
        pieces, missing = split_stream("1. 3, 11. 2. 1. 3. 2.", 3)
        self.assertEqual(missing, [])
        self.assertEqual(pieces[1], "3, 11.")
        self.assertEqual(pieces[2], "1.")

    def test_enumerate_without_counter_is_wildcard(self):
        # Mathpix сделал из строки «5. …» пункт enumerate и пронумеровал заново.
        stream = flatten_answer_stream(
            "\\begin{enumerate}\n\\item Первое. 2. \\(x=1\\). 3. 4. 4. 7.\n\\item \\(x=2\\). 6. 8.\n\\end{enumerate}")
        pieces, missing = split_stream(stream, 6)
        self.assertEqual(missing, [])
        self.assertEqual(pieces[5], r"\(x=2\).")

    def test_hint_split(self):
        self.assertEqual(
            split_answer_hint(r"\(n \pi\). Привести уравнение к виду \(x=0\)."),
            (r"\(n \pi\).", r"Привести уравнение к виду \(x=0\)."))
        self.assertEqual(
            split_answer_hint(r"Выразить \(\cos 2 x\) через \(\sin x\). Ответ: \(n \pi\)."),
            (r"\(n \pi\).", r"Выразить \(\cos 2 x\) через \(\sin x\)."))

    def test_stems(self):
        self.assertEqual(with_stem(r"\(|x-7|=4\)", None), r"Решите уравнение \(|x-7|=4\).")
        self.assertEqual(with_stem(r"\(x^{2}-x-1>0\).", None), r"Решите неравенство \(x^{2}-x-1>0\).")
        system = r"\(\left\{\begin{array}{l}x+y=1 \\ x-y=2\end{array}\right.\)"
        self.assertEqual(with_stem(system, None),
                         r"Решите систему уравнений \[\left\{\begin{array}{l}x+y=1 \\ x-y=2\end{array}\right.\]")
        self.assertEqual(with_stem(r"\(y=\cos 3 x, \quad y^{\prime}=?\)", None),
                         r"\(y=\cos 3 x, \quad y^{\prime}=?\)")
        self.assertEqual(with_stem("Решить уравнение \\(x=1\\).", None), "Решить уравнение \\(x=1\\).")

    def test_item_numbers(self):
        self.assertEqual(item_number(Item("-", "16 [2]. \\(x\\)"))[:3], (16, None, 2))
        self.assertEqual(item_number(Item("", "-3. \\(x\\)"))[:3], (3, None, None))
        self.assertEqual(item_number(Item("", "1-21. Построить треугольник по"))[:2], (1, 21))
        self.assertEqual(item_number(Item("b.", "\\(x\\)"))[0], 6)

    def test_heal_ocr(self):
        self.assertEqual(heal_ocr(r"\operatorname{si~} \mathrm{n} 2 x"), r"\sin 2 x")
        self.assertEqual(heal_ocr(r"si \(\mathrm{n}^{2} x\)"), r"\(\sin^{2} x\)")
        self.assertEqual(heal_ocr("()твет: 5"), "Ответ: 5")
        self.assertEqual(heal_ocr("Peшение."), "Решение.")

    def test_faculty_codes(self):
        self.assertEqual(faculty_codes("Химический ф-т и отд. геофизики геологического ф-та"), ["ГФ", "ХФ"])
        self.assertEqual(faculty_codes("Геологический факультет (отделение общей геологии)"), ["ГЛ"])
        self.assertEqual(faculty_codes("Биолого-почвенный факультет (отделение почвоведения)"), ["ПЧ"])
        self.assertEqual(faculty_codes("Отд. планирования и экономич. кибернетики экономич. ф-та"), ["ЭФ-ПК"])
        self.assertIn("ВМК", faculty_codes(
            "Факультет вычислительной математики и кибернетики (олимпиада, апрель 2005)"))

    def test_worked_split_keeps_remark(self):
        body = ("\\(x=1\\).\n\nРешение. Ясно.\n\nОтвет: \\(1\\).\n\n"
                "Замечание. Можно иначе.\n\nТеория следующей задачи.")
        text, solution, answer, warnings = split_worked(body)
        self.assertEqual(answer.strip(), r"\(1\).")
        self.assertIn("Замечание", solution)
        self.assertNotIn("Теория", solution)
        self.assertEqual(warnings, [])

    def test_override_drops_stale_image(self):
        # Рисунок OCR стоял в условии чужой задачи; правка условия без него.
        task = TaskDraft(external_id="Д24.2", source_number="Д24.2", source_path=["x"],
                         collection_key="x", collection_title="x", topic_original="x",
                         text_latex="\\(y=1\\)\n\\taskpic{1}", images=["ocr-265"])
        apply_override(task, {"text": "Найти касательные к \\(y=x\\)."})
        self.assertEqual(task.images, [])
        apply_override(task, {"solution": "См. рис.\n\\includegraphics{tkachuk-p294-1}"})
        self.assertEqual(task.images, [])
        kept = TaskDraft(external_id="Д1.1", source_number="Д1.1", source_path=["x"],
                         collection_key="x", collection_title="x", topic_original="x",
                         text_latex="\\taskpic{1}", images=["ocr-1"])
        apply_override(kept, {"answer": "\\(1\\)"})
        self.assertEqual(kept.images, ["ocr-1"])
