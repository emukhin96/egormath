import tempfile
import unittest
from pathlib import Path

from tools.ege_qa import audit, environment_balance_issues, risks, selections


def row(external_id, *, text="Достаточно длинное условие задачи.", answer="2",
        images=None, subitems=None, warnings=None, codes=None,
        solution=""):
    value = {
        "external_id": external_id,
        "text_latex": text,
        "author_answer_latex": answer,
        "author_solution_latex": solution,
    }
    if images is not None:
        value["images"] = images
    if subitems is not None:
        value["subitems"] = subitems
    if warnings is not None:
        value["warnings"] = warnings
    if codes is not None:
        value["exam_item_codes"] = codes
    return value


class RisksTests(unittest.TestCase):
    def test_latex_environments_are_balanced_across_task_parts_and_answers(self):
        balanced = row(
            "1.1.4",
            text=r"Условие \begin{tabular}{c} x \end{tabular} \left(x\right).",
            answer=r"\begin{aligned}x&=1\\y&=2\end{aligned}",
            subitems=[{"text_latex": r"\begin{enumerate} пункт \end{enumerate}"}],
        )
        self.assertEqual(environment_balance_issues(balanced["text_latex"]), [])
        self.assertNotIn("unbalanced_environments", risks(balanced))

    def test_unclosed_tabular_environment_is_reported(self):
        value = row(
            "1.1.5",
            text=r"Таблица \begin{tabular}{ll} условие",
        )
        self.assertEqual(
            environment_balance_issues(value["text_latex"]),
            ["unclosed_begin:tabular"],
        )
        self.assertIn("unbalanced_environments", risks(value))

    def test_math_and_ocr_signals_are_specific(self):
        clean = row("1.1.1", text=r"Длина равна 10 км, а знак записан как \$.")
        self.assertEqual(risks(clean), [])

        flagged = row(
            "1.1.2", text=r"Задача 12. 10км { незакрыто $x$",
            answer=r"\frac{1}{2}", warnings=["ocr"])
        self.assertEqual(
            risks(flagged),
            ["complex_answer", "ocr_leak",
             "parser_warning", "stuck_units", "unbalanced_braces"],
        )

    def test_subitems_and_missing_answer_are_reported_once(self):
        value = row("1.1.3", answer="", subitems=[{"text_latex": "Подпункт"}])
        self.assertEqual(risks(value), ["missing_answer", "subitems"])


class SelectionTests(unittest.TestCase):
    def test_pilot_has_80_unique_ids_across_20_sections(self):
        rows = [row(f"{section}.1.{task:02d}")
                for section in range(1, 20) for task in range(1, 6)]
        rows.append(row("20.1.01"))  # one-task section

        pilot, sample = selections(rows)

        self.assertEqual(len(pilot), 80)
        self.assertEqual(len(pilot), len(set(pilot)))
        self.assertIn("20.1.01", pilot)
        self.assertEqual(len(sample), len(rows))
        self.assertEqual((pilot, sample), selections(rows))
        self.assertEqual({int(key.split(".")[0]) for key in pilot}, set(range(1, 21)))


class AuditTests(unittest.TestCase):
    def test_audit_validates_images_references_and_metadata(self):
        good = row(
            "1.1.1", text=r"Условие с рисунком \taskpic{1}.",
            images=["diagram"], codes=["EGE_PROFILE_2027_01"])
        missing = row(
            "2.1.1", text=r"Условие \taskpic{2}.", images=["absent"],
            codes=["WRONG"])
        with tempfile.TemporaryDirectory() as directory:
            image_dir = Path(directory)
            (image_dir / "diagram.png").touch()
            report = audit(
                {"source": {"answers_file": "answers.pdf"},
                 "tasks": [good, missing]}, image_dir)

        self.assertEqual(report["tasks"]["1.1.1"]["risks"], [])
        self.assertEqual(
            report["tasks"]["2.1.1"]["risks"],
            ["exam_metadata", "image_reference", "missing_image"],
        )
        self.assertEqual(report["duplicates"], [])
        # A one-task section is deliberately included in the clean sample;
        # review_queue therefore contains both the sample and risky records.
        self.assertEqual(report["review_queue"], ["1.1.1", "2.1.1"])

    def test_audit_checks_image_references_in_author_solution(self):
        value = row(
            "3.1.1", images=["diagram"], solution=r"Решение \taskpic{2}.",
            codes=["EGE_PROFILE_2027_03"])
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "diagram.png").touch()
            report = audit(
                {"source": {"answers_file": "answers.pdf"}, "tasks": [value]},
                Path(directory),
            )
        self.assertIn("image_reference", report["tasks"]["3.1.1"]["risks"])


if __name__ == "__main__":
    unittest.main()
