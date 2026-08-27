import tempfile
import unittest
from pathlib import Path

from tools.textbook_parser import (
    numeric_markers,
    parse_galitsky,
    parse_shestakov,
    shestakov_markers,
    write_bundle,
    ImportBundle,
    path_at,
    sections,
)


class TextbookParserTests(unittest.TestCase):
    def test_section_path_replaces_sibling_at_same_level(self):
        text = (
            r"\section{Глава 1}\subsection{Тема A} задача "
            r"\subsection{Тема B} другая задача"
        )
        headings = sections(text)
        pos = text.index("другая задача")
        self.assertEqual(path_at(headings, pos), ["Глава 1", "Тема B"])

    def test_shestakov_normalizes_split_and_cyrillic_code(self):
        text = r"1.1.A01 one \item[1.1.] В02 two 2.3.С10 three"
        self.assertEqual(
            [item.external_id for item in shestakov_markers(text)],
            ["1.1.A01", "1.1.B02", "2.3.C10"],
        )

    def test_numeric_markers_only_accept_task_boundaries(self):
        text = "1.1. First\n\\item[1.2.] Second\nvalue 3.14. not a task"
        self.assertEqual(
            [item.external_id for item in numeric_markers(text)], ["1.1", "1.2"]
        )

    def test_galitsky_pairs_author_answer_and_solution(self):
        source = r"""
\section*{§ 1. ДРОБИ}
\section*{Упражнения}
\item[1.1.] Вычислите $1+1$.
\item[1.2.] Докажите тождество.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. 2. 1.2. Верно. Решение. Раскроем скобки.
"""
        tasks, diagnostics = parse_galitsky(source)
        self.assertEqual([task.external_id for task in tasks], ["1.1", "1.2"])
        self.assertEqual(tasks[0].author_answer_latex, "2.")
        self.assertIn("Решение", tasks[1].author_solution_latex)
        self.assertEqual(diagnostics["matched_solutions"], 2)

    def test_hint_is_kept_inside_solution(self):
        source = r"""
\section*{§ 1. ДРОБИ}
\item[1.1.] Докажите тождество.
\section*{ОТВЕТЫ, УКАЗАНИЯ, РЕШЕНИЯ}
1.1. Верно. Указание. Раскройте скобки. Решение. После сокращения получаем ноль.
"""
        tasks, _ = parse_galitsky(source)
        self.assertEqual(tasks[0].author_answer_latex, "Верно.")
        self.assertIn("Указание", tasks[0].author_solution_latex)
        self.assertIn("Решение", tasks[0].author_solution_latex)

    def test_parsed_tasks_always_have_zero_stars(self):
        task_text = r"\section*{§1. Целые числа} 1.1.A01 Найдите $1+1$."
        solution_text = r"1.1.A01 Ответ: 2."
        tasks, _ = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].stars, 0)

    def test_shestakov_pairs_separate_solution_book(self):
        task_text = r"\section*{§1. Целые числа} 1.1.A01 Найдите $1+1$."
        solution_text = r"1.1.A01 $1+1=2$. Ответ: 2."
        tasks, diagnostics = parse_shestakov(task_text, solution_text)
        self.assertEqual(tasks[0].author_answer_latex, "2.")
        self.assertEqual(diagnostics["matched_solutions"], 1)

    def test_writer_creates_three_review_artifacts(self):
        bundle = ImportBundle(1, "test", {}, [], {
            "tasks_with_subitems": 0,
            "tasks_with_author_answer": 0,
            "tasks_with_author_solution": 0,
            "review_counts": {},
        })
        with tempfile.TemporaryDirectory() as directory:
            write_bundle(bundle, Path(directory))
            self.assertEqual(
                {path.name for path in Path(directory).iterdir()},
                {"import.json", "review.tsv", "report.md"},
            )


if __name__ == "__main__":
    unittest.main()
