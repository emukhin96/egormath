"""Тесты профиля Коропец: OCR-фрагменты как в книге, а не идеальный TeX."""

import hashlib
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .koropets_parser import (
    break_chains, display_stem, parse_koropets, split_example, strip_labels)


STRUCTURE = {
    "grade_bands": ["GRADE_10_11"],
    "examples_title": "Примеры с решениями",
    "exercises_title": "Примеры для самостоятельного решения",
    "chapters": [
        {"number": 2, "title": "2. Неравенства, содержащие модули",
         "topic": "ALG.04.05", "examples": 2, "exercises": 2},
        {"number": 3, "title": "3. Иррациональные неравенства",
         "topic": "ALG.04.06", "examples": 1, "exercises": 1},
    ],
}

BOOK = r"""
\section*{СОДЕРЖАНИЕ}
2.2. Примеры с решениями ..... 11\\
2.3. Примеры для самостоятельного решения ..... 20\\
ЛИТЕРАТУРА ..... 125\\
\section*{1. МЕТОД ЗАМЕНЫ МНОЖИТЕЛЯ (МЗМ)}
Теория.
  \item НЕРАВЕНСТВА, СОДЕРЖАЩИЕ МОДУЛИ\\
2.1. Условия равносильности для МЗМ

2.2. Примеры с решениями

Пример 1. Решите неравенство \(\quad|x-1| \leq 2\).\\
Решение. \(|x-1|-2 \leq 0\).

\includegraphics[max width=\textwidth, alt={}, center]{scan-010_1}\\
Ответ: \([-1 ; 3]\).\\
Пример 2. Решите неравенство \(|x| \geq 1\).

Решение. Первый способ.

Ответ: \((-\infty ;-1]\).

Второй способ.

Ответ: \((-\infty ;-1] \cup[1 ;+\infty)\).

\section*{2.3. Примеры для самостоятельного решения}
Решите неравенства:

\begin{enumerate}
  \item \(|x-2|<1\).
  \item \(\left|x^{2}-3 x\right|-5 \mid \geq 0\).
\end{enumerate}

Ответы:

\begin{enumerate}
  \item (1; 3).
  \item \hspace{0pt} [-2; 5].
\end{enumerate}

\section*{3. ИРРАЦИОНАЛЬНЫЕ НЕРАВЕНСТВА}
\section*{3.2. Примеры с решениями}
Пример 1. Решите неравенство \(\sqrt{x}<2\)
\section*{Решение.}
\(0 \leq x<4\).

Ответ: [0; 4).
\section*{8.2. Использование ограниченности функций}
Теория раздела не входит в ответ.

\section*{3.3. Примеры для самостоятельного решения}
Решите неравенства:

\begin{enumerate}
  \item \(\sqrt{x}>1\).
\end{enumerate}

Ответы:

\begin{enumerate}
  \item \((1 ;+\infty)\).
\end{enumerate}

\section*{ЛИТЕРАТУРА}
"""


def parse(text=BOOK, repairs_path=Path("/nonexistent")):
    return parse_koropets(text, structure=STRUCTURE, repairs_path=repairs_path)


class KoropetsParserTests(SimpleTestCase):
    def test_examples_and_exercises_keys(self):
        tasks, diagnostics = parse()
        self.assertEqual(
            [t.external_id for t in tasks],
            ["П2.1", "П2.2", "2.1", "2.2", "П3.1", "3.1"])
        self.assertEqual(diagnostics["count_mismatch"], [])
        by_id = {t.external_id: t for t in tasks}
        self.assertEqual(by_id["П2.1"].source_path,
                         ["2. Неравенства, содержащие модули", "Примеры с решениями"])
        self.assertEqual(by_id["3.1"].topic_code, "ALG.04.06")
        self.assertEqual(by_id["2.1"].grade_band_codes, ["GRADE_10_11"])

    def test_example_fields(self):
        tasks, _ = parse()
        task = tasks[0]
        self.assertEqual(task.text_latex, r"Решите неравенство \[|x-1| \leq 2\]")
        self.assertIn(r"\taskpic{1}", task.author_solution_latex)
        self.assertNotIn("Ответ", task.author_solution_latex)
        self.assertIn("[-1 ; 3]", task.author_answer_latex)

    def test_last_answer_wins_and_earlier_stays_in_solution(self):
        tasks, _ = parse()
        task = tasks[1]
        self.assertIn("Второй способ", task.author_solution_latex)
        self.assertIn("Ответ", task.author_solution_latex)
        self.assertIn(r"[1 ;+\infty)", task.author_answer_latex)

    def test_answer_stops_before_next_theory_section(self):
        tasks, _ = parse()
        task = tasks[4]
        self.assertEqual(task.author_solution_latex, r"\(0 \leq x<4\).")
        self.assertEqual(task.author_answer_latex, r"\([0; 4)\).")

    def test_exercise_lead_and_bare_interval_answer(self):
        tasks, _ = parse()
        self.assertEqual(tasks[2].text_latex, r"Решите неравенство \[|x-2|<1\]")
        self.assertEqual(tasks[3].author_answer_latex, r"\([-2; 5]\).")

    def test_decimal_comma_in_answer(self):
        from .koropets_parser import _answer_text
        self.assertEqual(_answer_text(r"\{0,5\}."), r"\(\{0{,}5\}\).")
        self.assertEqual(_answer_text(r"(0,7; 0,8) \cup \{1; 2\}"), r"\((0{,}7; 0{,}8) \cup \{1; 2\}\).")

    def test_toc_is_not_a_section(self):
        _, diagnostics = parse()
        self.assertEqual(diagnostics["tasks_by_section"][
            "2. Неравенства, содержащие модули / Примеры для самостоятельного решения"], 2)

    def test_repairs_bound_to_source_hash(self):
        digest = hashlib.sha256(BOOK.encode("utf-8")).hexdigest()
        spec = {"editions": [{
            "source_sha256": digest,
            "patches": [{"id": "2.2-модуль", "source": "PDF с. 19",
                         "before": r"\left|x^{2}-3 x\right|-5 \mid",
                         "after": r"||x^{2}-3 x|-5|"}],
            "tasks": {"П2.1": {"solution": r"Скан: \includegraphics{koropets-p010-1}"}},
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repairs.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            tasks, diagnostics = parse(repairs_path=path)
            other, _ = parse(BOOK + "\n", repairs_path=path)
        by_id = {t.external_id: t for t in tasks}
        self.assertIn(r"||x^{2}-3 x|-5|", by_id["2.2"].text_latex)
        self.assertEqual(by_id["П2.1"].author_solution_latex, r"Скан: \taskpic{1}")
        self.assertEqual(by_id["П2.1"].images, ["koropets-p010-1"])
        self.assertEqual(diagnostics["overrides_applied"], ["П2.1"])
        # Другой скан: правки не применяются.
        self.assertIn(r"\mid", {t.external_id: t for t in other}["2.2"].text_latex)

    def test_condition_labels_removed(self):
        self.assertEqual(
            strip_labels(r"Решите систему неравенств \[\left\{\begin{array}{l} a<0, \\ b \geq 0 \end{array}\right. "
                         r"\quad \begin{array}{l} (1) \\ (2) \end{array}\]"),
            r"Решите систему неравенств \[\left\{\begin{array}{l} a<0, \\ b \geq 0 \end{array}\right.\]")
        self.assertEqual(
            strip_labels(r"Решите \[\left\{\begin{array}{l} a \geq 0, \quad (1) \\ b. \quad (2)\end{array}\right.\]"),
            r"Решите \[\left\{\begin{array}{l} a \geq 0, \\ b.\end{array}\right.\]")
        self.assertEqual(strip_labels(r"Решите неравенство \(x>1\) (1)"), r"Решите неравенство \(x>1\)")

    def test_display_stem_keeps_label(self):
        self.assertEqual(
            display_stem(r"Решите неравенство \(\displaystyle x>1\). \quad (1)"),
            r"Решите неравенство \[x>1 \quad (1)\]")
        self.assertEqual(
            display_stem(r"Решите систему неравенств \(\left\{\begin{array}{l}x>1, \\ x<2 .\end{array}\right.\)"),
            r"Решите систему неравенств \[\left\{\begin{array}{l}x>1, \\ x<2 .\end{array}\right.\]")
        # Условие с прозой внутри — не трогаем.
        text = r"Решите неравенство \(x>1\), если \(x<5\)."
        self.assertEqual(display_stem(text), text)

    def test_break_chains_top_level_only(self):
        value = (r"\[(1) \Leftrightarrow x^{2}-5x+6>0 \Leftrightarrow "
                 r"\left\{\begin{array}{l}b \Leftrightarrow c, \\ d\end{array}\right. \Leftrightarrow (x-2)(x-3)>0\]")
        self.assertEqual(break_chains(value), "\n".join([
            r"\[(1) \Leftrightarrow x^{2}-5x+6>0 \Leftrightarrow\]",
            r"\[\left\{\begin{array}{l}b \Leftrightarrow c, \\ d\end{array}\right. \Leftrightarrow\]",
            r"\[(x-2)(x-3)>0\]"]))

    def test_break_inline_chain_and_named_values(self):
        self.assertEqual(
            break_chains(r"Тогда \(f(x) \geq 0 \Leftrightarrow \left\{\begin{array}{l}a \Leftrightarrow b\end{array}\right.\), "
                         r"где \(f(x)=\log_{2}(x+1), g(x)=3^{x}\)."),
            r"Тогда \(f(x) \geq 0 \Leftrightarrow\) \(\left\{\begin{array}{l}a \Leftrightarrow b\end{array}\right.\), "
            r"где \(f(x)=\log_{2}(x+1)\), \(g(x)=3^{x}\).")
        # Интервалы и перечисления без «имя =» не режутся.
        value = r"\(x \in (1; 2) \cup \{3; 4\}\)"
        self.assertEqual(break_chains(value), value)

    def test_split_example_without_answer(self):
        stem, solution, answer = split_example(" Решите \\(x>0\\).\nРешение. Текст.")
        self.assertEqual(answer, "")
        self.assertIn("Текст", solution)

    def test_not_this_book(self):
        with self.assertRaises(ValueError):
            parse_koropets("Другая книга", structure=STRUCTURE)

    def test_missing_chapter_one_is_import_error(self):
        text = BOOK.replace(r"\section*{1. МЕТОД ЗАМЕНЫ МНОЖИТЕЛЯ (МЗМ)}", "Теория МЕТОД ЗАМЕНЫ МНОЖИТЕЛЯ")
        with self.assertRaisesMessage(ValueError, "начало главы 1"):
            parse(text)

    def test_missing_first_examples_section_is_import_error(self):
        text = BOOK.replace("2.2. Примеры с решениями\n\nПример 1.", "Пример 1.")
        with self.assertRaisesMessage(ValueError, "«Примеры с решениями» главы 2"):
            parse(text)


class KoropetsRepairsDataTests(SimpleTestCase):
    """Сверенные правки скана: целостность файла, без самого TEX."""

    def test_repairs_file_is_consistent(self):
        from .koropets_parser import REPAIRS_PATH, STRUCTURE_PATH
        spec = json.loads(REPAIRS_PATH.read_text(encoding="utf-8"))
        structure = json.loads(STRUCTURE_PATH.read_text(encoding="utf-8"))
        edition, = spec["editions"]
        self.assertEqual(len(edition["source_sha256"]), 64)
        chapters = {c["number"]: c for c in structure["chapters"]}
        for key, row in edition["tasks"].items():
            number, index = key.lstrip("П").split(".")
            limit = chapters[int(number)]["examples" if key.startswith("П") else "exercises"]
            self.assertTrue(1 <= int(index) <= limit, key)
            self.assertTrue({"text", "answer", "solution"} & set(row), key)
            self.assertTrue(row["source"].startswith("PDF с."), key)
        examples = [k for k in edition["tasks"] if k.startswith("П")]
        self.assertEqual(len(examples), sum(c["examples"] for c in chapters.values()))
        for patch in edition["patches"]:
            self.assertTrue(patch["before"] and patch["id"] and patch["source"])
