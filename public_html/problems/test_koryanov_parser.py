"""Тесты профиля Корянова: OCR-фрагменты как в книге, а не идеальный TeX."""

import hashlib
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .koryanov_parser import (
    answer_latex, answer_stream, apply_fixes, prepare_text, cyrillic_words, degrees, exercise_items,
    lift_display_answers, parse_koryanov, point_names, split_example, tidy)
from .textbook_parser import TaskDraft


STRUCTURE = {
    "grade_bands": ["GRADE_10_11"],
    "examples_title": "Примеры с решениями",
    "exercises_title": "Тренировочные упражнения",
    "examples_total": 5,
    "exercises_total": 5,
    "body_start": r"\section*{Глава 1. Расстояния и углы}",
    "body_end": r"\section*{3.4. Опорные задачи}",
    "answers_start": r"\section*{Ответы и указания}",
    "answers_end": r"\section*{Список и источники литературы}",
    "chapters": [
        {"number": 1, "title": "1. Расстояния и углы"},
        {"number": 2, "title": "2. Площади и объёмы", "exercises": [5, 5]},
    ],
    "paragraphs": [
        {"key": "1.1", "chapter": 1, "heading": "1.1. Расстояние между двумя точками",
         "title": "1.1. Расстояние между двумя точками", "topic": "GEO.08.04",
         "examples": [1, 3], "exercises": [1, 2]},
        {"key": "1.3", "chapter": 1, "heading": "3. Расстояние от точки до плоскости",
         "title": "1.3. Расстояние от точки до плоскости", "topic": "GEO.08.04",
         "examples": [4, 4], "exercises": [3, 4]},
        {"key": "2.3", "chapter": 2, "heading": "2.3. Объём многогранника",
         "title": "2.3. Объём многогранника", "topic": "GEO.09.06",
         "examples": [5, 5]},
    ],
    "methods": [
        {"title": "Поэтапно-вычислительный метод", "method": ""},
        {"title": "Координатный метод", "method": "COORDINATE"},
        {"title": "Метод параллельных прямых", "method": ""},
        {"title": "Метод объёмов", "method": ""},
    ],
    "extra_solutions": [
        {"task": "П1", "anchor": "Решим указанным методом пример 1.",
         "title": "Другой способ (метод параллельных прямых)."},
    ],
    "topics": {"5": "GEO.09.06"},
}

BOOK = r"""
\title{МАТЕМАТИКА. ЕГЭ 2013 \\
 Многогранники: \\
 типы задач и методы их решения \\
 (типовые задания С2) }
\section*{Глава 1. Расстояния и углы}
\section*{1.1. Расстояние между двумя точками}
\section*{Поэтапно-вычислительный метод}
Пример 1. \(B\) единичном кубе \(A B C D A_{1} B_{1} C_{1} D_{1}\) найти длину отрезка \(E F\).

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{scan-003_459_482_1878_440}
\captionsetup{labelformat=empty}
\caption{Рис. 1}
\end{center}
\end{figure}

Peшeние. Из равно-

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{scan-003_100_100_100_100}
\captionsetup{labelformat=empty}
\caption{Рис. 4}
\end{center}
\end{figure}

бедренного треугольника \(D_{1} E F\) (см. рис. 1) находим ответ.

\[
\begin{aligned}
E F= & \sqrt{2} . \quad \text { Ombem: } \sqrt{2} .
\end{aligned}
\]

Замечание. Можно и векторами.

\section*{Координатный метод}
Пример 2. В правильной пирамиде MABCD точка F - середина ребра МС. Найти угол между плоскостью и прямой ВF (см. рис. 2).

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{scan-004_400_400_100_100}
\captionsetup{labelformat=empty}
\caption{Рис. 2}
\end{center}
\end{figure}

Peueние. 1-й способ. Угол равен 30°.

Ответ: 30°.\\
2-й способ. Тот же угол, как показано на рисунке 2.

Ответ: \(30^{\circ}\).\\
Метод объёмов\\
Теория метода объёмов в пример не входит.

Пример 3. Найти расстояние, длина ребра равна \(а\).

Решение. Ребро равно \(a\).

Ответ:

\[
\frac{a \sqrt{3}}{3} .
\]

\section*{Метод параллельных прямых}
Решим указанным методом пример 1.\\
Решение. В квадрате диагональ равна \(\sqrt{2}\) (см. рис. 3).

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{scan-005_300_300_200_200}
\captionsetup{labelformat=empty}
\caption{Рис. 3}
\end{center}
\end{figure}

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{scan-005_200_200_900_900}
\captionsetup{labelformat=empty}
\caption{Рис. 5}
\end{center}
\end{figure}

Ответ: \(\sqrt{2}\).

Теория метода параллельных прямых.

\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{scan-005_100_100_950_950}
\captionsetup{labelformat=empty}
\caption{Рис. 6}
\end{center}
\end{figure}

\section*{Тренировочные упражнения}
\begin{enumerate}
  \item Ребра призмы равны 1, 4 и 4. Найдите расстояние.
  \item В призме найдите расстояние от точки \(A\) до прямой: a) \(D E\); б) \(D_{1} E_{1}\).
\end{enumerate}

\section*{3. Расстояние от точки до плоскости}
Пример 4. Найти расстояние от точки \(S\) до плоскости.

Решение. Опустим перпендикуляр.

Ответ: 2.\\
Если плоскости параллельны, то это теория параграфа.

\section*{Тренировочные упражнения}
\begin{enumerate}
  \setcounter{enumi}{2}
  \item В кубе найдите расстояние, если ребро
\end{enumerate}

равно 2.\\
4. Ребро \(A D\) пирамиды \(D A B C\) равно \(2 \sqrt{30} . C D\) - высота пирамиды.

\section*{Глава 2. Площади и объёмы}
\section*{2.3. Объём многогранника}
Пример 5. Площадь основания пирамиды равна 3. Найти объём части пирамиды.

Решение. Обозначим сечения (см. рис. 109).

Рис. 109

Ответ: 1.

\section*{Тренировочные упражнения}
\begin{enumerate}
  \setcounter{enumi}{4}
  \item Найдите объём пирамиды.
\end{enumerate}

Глава 3. Дополнения

\section*{3.4. Опорные задачи}
\begin{enumerate}
  \item Опорная задача в импорт не входит.
\end{enumerate}

\section*{Ответы и указания}
\begin{enumerate}
  \item
  \begin{enumerate}
    \setcounter{enumii}{1}
    \item
    \begin{enumerate}
      \setcounter{enumiii}{1}
      \item \(\sqrt{3}\). 3. 5. 4. 2,4.\\
5. \(\frac{a b c}{2}\). Указание. Использовать формулу.
    \end{enumerate}
  \end{enumerate}
\end{enumerate}

\section*{Список и источники литературы}
"""

LOST_FIRST = (
    "\\setcounter{enumiii}{1}\n      \\item \\(\\sqrt{3}\\). 3.",
    "\\setcounter{enumiii}{0}\n      \\item 3. 2. a) \\(\\sqrt{3}\\); б) 2. 3.",
)


def repairs_file(text: str, **edition) -> Path:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = {"editions": [{"source_sha256": digest, **edition}]}
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(spec, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


def parse(text=BOOK, **edition):
    edition.setdefault("patches", [{"id": "answers-1", "source": "PDF с. 100",
                                    "before": LOST_FIRST[0], "after": LOST_FIRST[1]}])
    edition.setdefault("figures", {"109": "koryanov-p074-1"})
    return parse_koryanov(text, structure=STRUCTURE, repairs_path=repairs_file(text, **edition))


class KoryanovParserTests(SimpleTestCase):
    def setUp(self):
        self.tasks, self.diagnostics = parse()
        self.by_id = {task.external_id: task for task in self.tasks}

    def test_keys_paths_and_topics(self):
        self.assertEqual([t.external_id for t in self.tasks],
                         ["П1", "П2", "П3", "1", "2", "П4", "3", "4", "П5", "5"])
        self.assertEqual(self.diagnostics["count_mismatch"], [])
        self.assertEqual(self.by_id["П4"].source_path,
                         ["1. Расстояния и углы", "1.3. Расстояние от точки до плоскости",
                          "Примеры с решениями"])
        # Упражнения главы 2 — одним блоком главы, тема — из таблицы.
        self.assertEqual(self.by_id["5"].source_path,
                         ["2. Площади и объёмы", "Тренировочные упражнения"])
        self.assertEqual(self.by_id["5"].topic_code, "GEO.09.06")
        self.assertEqual(self.by_id["П5"].topic_code, "GEO.09.06")
        self.assertEqual(self.by_id["П1"].grade_band_codes, ["GRADE_10_11"])
        # Метод — по подзаголовку, и \section*, и строкой «Метод объёмов\\».
        self.assertEqual(self.diagnostics["methods"]["П2"], ["Координатный метод", "COORDINATE"])
        self.assertEqual(self.diagnostics["methods"]["П3"], ["Метод объёмов", ""])

    def test_example_fields(self):
        first = self.by_id["П1"]
        # «\(B\) единичном кубе» — предлог «В»; «Peшeние» — латиница OCR.
        self.assertTrue(first.text_latex.startswith("В единичном кубе"))
        self.assertNotIn("Решение", first.text_latex)
        # Ответ OCR спрятал в выносную формулу.
        self.assertEqual(first.author_answer_latex, r"\(\sqrt{2}\)")
        self.assertNotIn("Ombem", first.author_solution_latex)
        self.assertIn("Замечание. Можно и векторами.", first.author_solution_latex)
        # Перенос слова через рисунок, на который пример не ссылается (теория).
        self.assertIn("Из равнобедренного треугольника", first.author_solution_latex)
        # Решение из теории другого метода («Решим указанным методом пример 1»).
        self.assertIn("Другой способ (метод параллельных прямых). В квадрате",
                      first.author_solution_latex)
        # Ответ второго способа совпадает с ответом примера — в разборе не дублируется.
        self.assertNotIn("Ответ:", first.author_solution_latex)
        self.assertEqual(self.diagnostics["extra_solutions"], ["П1"])

    def test_multiple_methods_keep_intermediate_answer(self):
        second = self.by_id["П2"]
        self.assertIn("2-й способ", second.author_solution_latex)
        self.assertIn("Ответ:", second.author_solution_latex)
        self.assertEqual(second.author_answer_latex, r"\(30^{\circ}\)")
        self.assertNotIn("Теория метода объёмов", second.author_solution_latex)
        # Обозначения точек кириллицей и вне формулы — в формулу латиницей.
        self.assertIn(r"\(MABCD\)", second.text_latex)
        self.assertIn(r"\(MC\)", second.text_latex)
        self.assertIn(r"\(BF\)", second.text_latex)

    def test_display_answer_and_cyrillic_letter(self):
        third = self.by_id["П3"]
        self.assertEqual(third.author_answer_latex, r"\(\frac{a \sqrt{3}}{3}\)")
        self.assertIn(r"равна \(a\)", third.text_latex)

    def test_theory_after_answer_is_dropped(self):
        self.assertEqual(self.by_id["П4"].author_answer_latex, "$2$")
        self.assertNotIn("теория параграфа", self.by_id["П4"].author_solution_latex)

    def test_figures_follow_references(self):
        first, second = self.by_id["П1"], self.by_id["П2"]
        # Рисунок 1 — ссылка в разборе, рисунок 3 — в дополнительном решении.
        self.assertEqual(first.images, ["scan-003_459_482_1878_440", "scan-005_300_300_200_200",
                                        "scan-003_100_100_100_100", "scan-005_200_200_900_900"])
        # Рисунки без ссылки внутри разбора (4) и внутри дополнительного решения
        # из теории (5) — в конец разбора, с предупреждением.
        self.assertEqual(self.diagnostics["figures_positional"], {"П1": ["4", "5"]})
        # Рисунок теории после ответа дополнительного решения — не в разбор.
        self.assertIn("6", self.diagnostics["figures_unreferenced"])
        self.assertTrue(first.author_solution_latex.endswith(r"\taskpic{3}" + "\n\n" + r"\taskpic{4}"))
        self.assertIn("Рисунок без ссылки привязан по положению: проверить", first.warnings)
        self.assertNotIn(r"\taskpic", first.text_latex)
        self.assertIn(r"\taskpic{1}", first.author_solution_latex)
        self.assertNotIn("рис. 1", first.author_solution_latex)
        # Ссылка в условии — рисунок в условии; повторная — «на рисунке».
        self.assertIn(r"\taskpic{1}", second.text_latex)
        self.assertIn("как показано на рисунке.", second.author_solution_latex)
        # Рисунок, который OCR потерял, — вырезка из PDF по сверенной правке.
        self.assertEqual(self.by_id["П5"].images, ["koryanov-p074-1"])
        self.assertEqual(self.diagnostics["figures_missing_by_task"], {})

    def test_exercises_numbers_and_answers(self):
        self.assertEqual(self.by_id["1"].author_answer_latex, "$3$")
        two = self.by_id["2"]
        self.assertEqual([item.label for item in two.subitems], ["а", "б"])
        self.assertEqual([item.author_answer_latex for item in two.subitems],
                         [r"\(\sqrt{3}\)", "$2$"])
        self.assertEqual(two.author_answer_latex, "")
        # Перенос колонки после \end{enumerate} — продолжение пункта.
        self.assertIn("равно $2$", self.by_id["3"].text_latex)
        # «\(2 \sqrt{30} . C D\)» — конец фразы в формуле.
        self.assertIn(r"\(2 \sqrt{30}\). \(C D\)", self.by_id["4"].text_latex)
        self.assertEqual(self.by_id["4"].author_answer_latex, "$2{,}4$")
        five = self.by_id["5"]
        self.assertEqual(five.author_answer_latex, r"\(\frac{a b c}{2}\)")
        self.assertEqual(five.author_solution_latex, "Указание. Использовать формулу.")
        self.assertEqual(self.diagnostics["answer_stream_problems"], [])
        self.assertEqual(self.diagnostics["source_repairs_applied"], ["answers-1"])

    def test_not_this_book(self):
        with self.assertRaises(ValueError):
            parse_koryanov("Другая книга", structure=STRUCTURE)

    def test_repairs_only_for_same_scan(self):
        other = repairs_file("другой текст", patches=[
            {"id": "x", "source": "PDF с. 1", "before": LOST_FIRST[0], "after": LOST_FIRST[1]}])
        tasks, diagnostics = parse_koryanov(BOOK, structure=STRUCTURE, repairs_path=other)
        self.assertEqual(diagnostics["source_repairs_applied"], [])
        # Без правки ответ 1 потерян, как в OCR.
        self.assertIn("1", diagnostics["missing_answers"])
        self.assertTrue(any("пропущены" in p for p in diagnostics["answer_stream_problems"]))


class KoryanovHelpersTests(SimpleTestCase):
    def test_answer_stream_counters_and_numbers_in_formula(self):
        zone = (r"\begin{enumerate}" "\n" r"\setcounter{enumi}{48}" "\n"
                r"  \item \(\frac{3 \sqrt{46}}{\sqrt{239}} . \mathbf{5 0 .} \frac{60}{7}\). 51. 2,4. 52. 3."
                "\n" r"  \item \(1\). 54. 130 . 55. 7." "\n" r"\end{enumerate}")
        answers, problems = answer_stream(zone, 0)
        # Номер в формуле OCR («\mathbf{5 0 .}») закрывает формулу.
        self.assertEqual(answers[49], r"\(\frac{3 \sqrt{46}}{\sqrt{239}}\).")
        self.assertEqual(answers[50], r"\(\frac{60}{7}\).")
        # «2,4.» и «130 .» — числа ответа, а не номера.
        self.assertEqual(answers[51], "2,4.")
        self.assertEqual(answers[52], "3.")
        # Пункт списка без счётчика — следующий номер.
        self.assertEqual(answers[53], r"\(1\).")
        self.assertEqual(answers[54], "130 .")
        self.assertEqual(answers[55], "7.")
        # Фрагмент начинается с 49 — пропуск 1–48 виден в диагностике.
        self.assertEqual(problems, ["после 0 идёт 49: пропущены ответы"])

    def test_answer_latex(self):
        self.assertEqual(answer_latex("60°."), (r"\(60^{\circ}\)", ""))
        self.assertEqual(answer_latex(r"a) \(\frac{\sqrt{2}}{4}\); б) \(\frac{1}{4}\)."),
                         (r"а) \(\frac{\sqrt{2}}{4}\); б) \(\frac{1}{4}\)", ""))
        # «(a+b)» внутри формулы — не метка пункта.
        self.assertEqual(answer_latex(r"\(\sqrt{2 h^{2}+(a+b)^{2}}\)")[0],
                         r"\(\sqrt{2 h^{2}+(a+b)^{2}}\)")

    def test_split_example_continuations(self):
        parts = split_example(" Условие.\n\nРешение. Шаг.\n\nОтвет: 1.\\\\\nРешение. 2-й способ. Ещё.\n\nОтвет: 1.\n\nТеория.")
        self.assertIn("2-й способ", parts.solution)
        self.assertEqual(parts.answer.strip(), "1.")
        self.assertIn("Теория", parts.dropped)

    def test_exercise_items(self):
        zone = ("\\begin{enumerate}\n  \\setcounter{enumi}{6}\n  \\item Семь.\n  \\item Восемь\n"
                "\\end{enumerate}\n\nконец.\\\\\n9. Девять.\n")
        self.assertEqual(exercise_items(zone), [(7, "Семь."), (8, "Восемь\n\n\nконец.\\\\"), (9, "Девять.")])

    def test_lift_display_answers(self):
        value = "\\[\n\\begin{aligned}\nS= & a^{2} . \\\\\n\\text { Ответ: } & a^{2} .\n\\end{aligned}\n\\]"
        self.assertEqual(lift_display_answers(value),
                         "\\[\n\\begin{aligned}\nS= & a^{2} .\n\\end{aligned}\n\\]\n\nОтвет: \\(a^{2}\\).")

    def test_prose_fixes(self):
        self.assertEqual(cyrillic_words("ребpa paвен coomветственно, \\(a p\\)"),
                         "ребра равен соответственно, \\(a p\\)")
        self.assertEqual(point_names("пирамиде SABCD (МИОО, ЕГЭ)"), "пирамиде \\(SABCD\\) (МИОО, ЕГЭ)")
        self.assertEqual(degrees("угол 30° и \\(60°\\)"), "угол \\(30^{\\circ}\\) и \\(60^{\\circ}\\)")

    def test_tidy(self):
        self.assertEqual(tidy("(МИОО, $2010$). в правильной"), "(МИОО, 2010). В правильной")
        self.assertEqual(tidy("$1$-й способ (поэтапновычислительный)"), "1-й способ (поэтапно-вычислительный)")
        self.assertEqual(tidy("где \\(\\varphi-\\) искомый угол"), "где \\(\\varphi\\) — искомый угол")
        self.assertEqual(tidy("точки \\(P\\), М и \\(K\\); [Л.М. Атанасян]"),
                         "точки \\(P\\), \\(M\\) и \\(K\\); [Л.М. Атанасян]")
        self.assertEqual(tidy("у \\(\\) которого co стороной, т.e. основания а."),
                         "у которого со стороной, т.е. основания \\(a\\).")

    def test_lengths_list_keeps_decimal_comma(self):
        self.assertEqual(prepare_text("равны \\(6 с м, 2,5 см\\) и"), "равны \\(6\\) см, \\(2,5\\) см и")
        self.assertEqual(prepare_text("\\(2,5 см, 3 см\\)"), "\\(2,5\\) см, \\(3\\) см")

    def test_tidy_splits_equalities_list(self):
        self.assertEqual(tidy("что \\(A C=B D=14, \\quad B C=A D=13\\). Найдите"),
                         "что \\(A C=B D=14\\), \\(B C=A D=13\\). Найдите")
        # Перечень точек без равенств — одна формула.
        value = "точки \\(M, \\quad N\\)"
        self.assertEqual(tidy(value), value)

    def test_apply_fixes(self):
        task = TaskDraft("П1", "П1", [], "", "", "", "Найти \\(x\\).")
        diagnostics = {"fixes_applied": [], "fixes_skipped": [], "fixes_failed": []}
        fixes = [{"id": "a", "task": "П1", "field": "text", "old": "\\(x\\)", "new": "\\(y\\)"},
                 {"id": "b", "task": "П1", "field": "text", "old": "\\(z\\)", "new": "\\(y\\)"},
                 {"id": "c", "task": "П1", "field": "text", "old": "\\(w\\)", "new": "\\(v\\)"},
                 {"id": "d", "task": "П2", "field": "text", "old": "\\(x\\)", "new": "\\(v\\)"}]
        apply_fixes(task, fixes, diagnostics)
        self.assertEqual(task.text_latex, "Найти \\(y\\).")
        # «b» уже сделана общим правилом, «c» не нашлась — в диагностику.
        self.assertEqual(diagnostics["fixes_applied"], ["a"])
        self.assertEqual(diagnostics["fixes_skipped"], ["b"])
        self.assertEqual(len(diagnostics["fixes_failed"]), 1)


class KoryanovRepairsDataTests(SimpleTestCase):
    """Сверенные правки скана: целостность файлов, без самого TEX."""

    def test_repairs_and_structure_are_consistent(self):
        from .koryanov_parser import REPAIRS_PATH, STRUCTURE_PATH
        spec = json.loads(REPAIRS_PATH.read_text(encoding="utf-8"))
        structure = json.loads(STRUCTURE_PATH.read_text(encoding="utf-8"))
        edition, = spec["editions"]
        self.assertEqual(len(edition["source_sha256"]), 64)
        self.assertEqual(len(edition["pdf_sha256"]), 64)
        for patch in edition["patches"]:
            self.assertTrue(patch["before"] and patch["id"] and patch["source"].startswith("PDF с."))
        for key, row in edition["tasks"].items():
            number = int(key.lstrip("П"))
            limit = structure["examples_total" if key.startswith("П") else "exercises_total"]
            self.assertTrue(1 <= number <= limit, key)
            self.assertTrue({"text", "answer", "solution"} & set(row), key)
            self.assertTrue(row["source"].startswith("PDF с."), key)
        crops = {crop["name"] for crop in edition["crops"]}
        self.assertEqual(set(edition["figures"].values()), crops)
        # Примеры и упражнения параграфов идут подряд и покрывают всю книгу.
        examples = [n for p in structure["paragraphs"] if "examples" in p
                    for n in range(p["examples"][0], p["examples"][1] + 1)]
        self.assertEqual(examples, list(range(1, structure["examples_total"] + 1)))
        exercises = [n for p in structure["paragraphs"] if "exercises" in p
                     for n in range(p["exercises"][0], p["exercises"][1] + 1)]
        exercises += [n for c in structure["chapters"] if "exercises" in c
                      for n in range(c["exercises"][0], c["exercises"][1] + 1)]
        self.assertEqual(exercises, list(range(1, structure["exercises_total"] + 1)))
        codes = {"", "COORDINATE", "VECTOR", "TRIG", "EXTRA_CONSTRUCTION"}
        for method in structure["methods"]:
            self.assertTrue(set(method["method"].split()) <= codes, method)
