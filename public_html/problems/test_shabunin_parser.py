"""Тесты профиля Шабунина: OCR-фрагменты как в книге, а не идеальный TeX."""

from django.test import SimpleTestCase, TestCase

from .latex_utils import heal_split_math_dollars
from .models import Topic
from .shabunin_parser import (
    load_structure, normalize_cyrillic_units, parse_shabunin, source_path,
    topic_code)
from .test_textbook_import import bundle, make_teacher
from .textbook_import import create_batch_from_bundle
from .textbook_parser import (
    _open_paren_depth, apply_imported_answer, apply_imported_math,
    strip_subitem_punct)


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
\section*{АЛГЕБРАИЧЕСКИЕ УРАВНЕНИЯ И НЕРАВЕНСТВА}
\section*{§1. РАЦИОНАЛЬНЫЕ УРАВНЕНИЯ}
\section*{Первый уровень}
\begin{itemize}
  \item[IV.] 1. Определить графически число корней уравнения:\\
1) $x^{2}+1=\frac{1}{x}$;\\
2) $(x+1)^{3}=\frac{2}{x}$.
\end{itemize}

Решить уравнение (IV.2-\\
IV.4).

\begin{itemize}
  \item[IV.] 2.\\
1) $\frac{x^{3}-1}{x-1}-x-2=0$;\\
2) $\frac{8 x^{3}+1}{2 x+1}=2-2 x$.
  \item[IV.] 3 1) $x^{6}=7 x^{3}+8$;\\
2) $x^{6}+27=28 x^{3}$.
\end{itemize}
IV.4. Найти все значения параметра $a$, при которых уравнение $x^{2}=a$ имеет корни.

\section*{Второй уровень}
Решить уравнение (IV.5-IV.6).\\
IV.5.

\begin{enumerate}
  \item $x^{4}=1$;
  \item $x^{4}=16$.\\
IV.6.
  \item $x^{3}=8$;
  \item $x^{3}=27$.
\end{enumerate}

IV.7. Поезд прошёл $120 к м$ за $2 ч$. Найти его скорость. IV.8. Доказать, что $x^{2} \geqslant 0$.

\section*{ЗАДАЧИ ПОВЫШЕННОЙ СЛОЖНОСТИ К ГЛАВЕ IV}
\begin{itemize}
  \item[IV.] 9. Решить неравенство $x^{2}<1$.
\end{itemize}

\section*{ОТВЕТЫ К ГЛАВЕ IV}
IV.1. 1) Один; 2) два. IV.2. 1) -1 ; 2) 0,5.\\
IV.3. 1) -1; 2; 2) 1; 3. IV.4. $\left(-\infty ; 2] \cup\{11\} ; 2) a<8\right.$.\\
IV.5. 1) $\pm 1$;

\begin{enumerate}
  \item $\pm 2$.\\
IV.6. 1) 2; 2) 3.
\end{enumerate}
 IV.7. $60 к м / u$. IV.9. $(-1 ; 1)$. Рис. 1.
""" + FIGURE % ("uuid-077_1", "1") + r"""
\section*{КОМПЛЕКСНЫЕ ЧИСЛА}
"""


def parse_book():
    tasks, diagnostics = parse_shabunin(BOOK)
    return {task.external_id: task for task in tasks}, diagnostics


class ShabuninParserTests(SimpleTestCase):
    def test_markers_cover_item_inline_and_dotless_numbers(self):
        tasks, diagnostics = parse_book()
        self.assertEqual(
            list(tasks), [f"IV.{number}" for number in range(1, 10)])
        self.assertEqual(diagnostics["missing_task_ids"], [])

    def test_range_stem_is_prepended_without_source_numbers(self):
        tasks, diagnostics = parse_book()
        self.assertEqual(tasks["IV.2"].text_latex, "Решить уравнение:")
        self.assertEqual(
            [item.label for item in tasks["IV.2"].subitems], ["1", "2"])
        self.assertNotIn("IV.", tasks["IV.1"].text_latex)
        self.assertNotIn("Решить", tasks["IV.1"].subitems[-1].text_latex)
        # Собственное задание задачи серии заменяет общую формулировку.
        self.assertTrue(tasks["IV.4"].text_latex.startswith("Найти все"))
        self.assertEqual(diagnostics["range_stems"][0]["last"], "IV.4")

    def test_enumerate_numbering_restarts_at_each_task(self):
        tasks, _diagnostics = parse_book()
        self.assertEqual([item.text_latex for item in tasks["IV.6"].subitems],
                         ["$x^{3}=8$", "$x^{3}=27$"])
        self.assertEqual([item.label for item in tasks["IV.6"].subitems],
                         ["1", "2"])

    def test_answers_are_distributed_to_numeric_subitems(self):
        tasks, _diagnostics = parse_book()
        self.assertEqual(
            [item.author_answer_latex for item in tasks["IV.2"].subitems],
            ["$-1$", "$0,5$"])
        # Безымянный \item ответа продолжает отсчёт после «1)» в строке номера.
        self.assertEqual(
            [item.author_answer_latex for item in tasks["IV.5"].subitems],
            [r"$\pm 1$", r"$\pm 2$"])

    def test_paths_levels_and_hard_section(self):
        tasks, _diagnostics = parse_book()
        self.assertEqual(tasks["IV.1"].source_path, [
            "Глава 4. Алгебраические уравнения и неравенства",
            "§ 1. Рациональные уравнения", "Первый уровень"])
        chapter = load_structure()["IV"]
        self.assertEqual(source_path(chapter, 240), [
            "Глава 4. Алгебраические уравнения и неравенства",
            "Задачи повышенной сложности"])
        self.assertEqual(tasks["IV.1"].collection_title,
                         "Глава 4. Алгебраические уравнения и неравенства")
        self.assertEqual(tasks["IV.1"].topic_original,
                         "§ 1. Рациональные уравнения")

    def test_level_does_not_leak_into_paragraph_without_levels(self):
        chapter = load_structure()["V"]
        self.assertEqual(source_path(chapter, 56)[-1], "Первый уровень")
        self.assertEqual(source_path(chapter, 60)[-1], "Второй уровень")
        self.assertEqual(source_path(chapter, 70)[-1],
                         "§ 3. Тригонометрические формулы")

    def test_topic_code_by_paragraph_and_task_kind(self):
        chapter = load_structure()["IV"]
        self.assertEqual(topic_code(chapter, 1, "Решить уравнение"), "ALG.03.14")
        self.assertEqual(topic_code(chapter, 240, "Решить неравенство"), "ALG.04")
        self.assertEqual(topic_code(chapter, 240, "Решить уравнение"), "ALG.03")

    def test_answer_figure_reference_becomes_taskpic(self):
        tasks, diagnostics = parse_book()
        task = tasks["IV.9"]
        self.assertEqual(task.images, ["uuid-077_1"])
        self.assertIn(r"\taskpic{1}", task.author_answer_latex)
        self.assertEqual(diagnostics["answer_figures_unreferenced"], [])

    def test_units_become_text_after_numbers(self):
        tasks, _diagnostics = parse_book()
        self.assertIn("$120$ км", tasks["IV.7"].text_latex)
        self.assertIn("$2$ ч", tasks["IV.7"].text_latex)
        self.assertEqual(tasks["IV.7"].author_answer_latex, "$60$ км/ч")
        self.assertEqual(normalize_cyrillic_units(r"$x=3 м, y=4 м$"),
                         "$x=3$ м, $y=4$ м")
        self.assertEqual(normalize_cyrillic_units(r"$g=9,8 м / c^{2}$"),
                         "$g=9,8$ м/с$^{2}$")
        # Латинская c без единицы рядом — переменная.
        self.assertEqual(normalize_cyrillic_units("$a+2 c$"), "$a+2 c$")


class SharedNormalizationTests(SimpleTestCase):
    def test_whole_formula_with_left_right_keeps_its_dollars(self):
        value = r"$\forall a, b, c\left(x \neq 0\right)$"
        self.assertEqual(heal_split_math_dollars(value), value)
        self.assertEqual(
            heal_split_math_dollars(r"$\left(-\frac{7}{6}$ ;$-2\right)$"),
            r"$\left(-\frac{7}{6} ;-2\right)$")

    def test_lost_opening_dollar_still_heals_split_pair(self):
        # Открывающий доллар потерян: половина пары осталась вне ``$…$``.
        self.assertEqual(
            heal_split_math_dollars(r"\left(-\frac{7}{6}$ ;$-2\right)"),
            r"$\left(-\frac{7}{6} ;-2\right)$")
        self.assertEqual(heal_split_math_dollars(r"\{-2$; $1\}"), r"$\{-2; 1\}$")
        self.assertEqual(
            apply_imported_math(r"\left(-\frac{7}{6}$ ;$-2\right)"),
            r"$\displaystyle \left(-\frac{7}{6} ;-2\right)$")
        self.assertEqual(apply_imported_math(r"\{-2$; $1\}"), r"$\{-2; 1\}$")
        # Целые пары вне формулы разрывом не считаются.
        for value in (r"$\left(x\right)$ и \left(y\right)", r"$a$ \{b\} $c$"):
            self.assertEqual(heal_split_math_dollars(value), value)

    def test_split_pair_inside_sentence_is_healed_locally(self):
        # Русский текст вокруг разрыва склейке не мешает: склеивается
        # только отрезок разорванной пары.
        self.assertEqual(
            apply_imported_math(
                r"Найдите $x \in \left(-\frac{7}{6}$ ;$-2\right)$, при которых"),
            r"Найдите $\displaystyle x \in \left(-\frac{7}{6} ;-2\right)$, при которых")
        # Многоточие внутри множества не обрывает склеенную формулу.
        value = r"$\{3, 7, 11, 15, 19,$ ...$\}$"
        self.assertEqual(apply_imported_math(value), r"$\{3, 7, 11, 15, 19, ...\}$")
        self.assertEqual(apply_imported_math(apply_imported_math(value)),
                         apply_imported_math(value))

    def test_prose_between_formulas_is_not_a_split_pair(self):
        # Скобки множества вокруг фразы OCR: доллары на месте, фраза — текст.
        for value in (
                r"Истинно, $\bar{A} \equiv\left\{\right.$ Число $1917^{1941}$ "
                r"делится на $1941^{2}$ и не делится на 1941\}.",
                r"$A \equiv \{$Число 54 делится на 2 или на 3 \}"):
            self.assertEqual(heal_split_math_dollars(value), value)
        self.assertEqual(
            apply_imported_answer(r"Истинно, $\bar{A} \equiv\left\{\right.$ Число"),
            r"Истинно, $\bar{A} \equiv\left\{\right.$ Число")

    def test_interval_brackets_close_paren_depth(self):
        self.assertEqual(_open_paren_depth(r"(-\infty ; 2] \cup\{11\} "), 0)
        self.assertEqual(_open_paren_depth("(1; "), 1)

    def test_subitem_punct_keeps_right_delimiter_dot(self):
        value = r"F=\left\{\begin{array}{l}0 \\ 1\end{array}\right."
        self.assertEqual(strip_subitem_punct(value), value)


class ShabuninTopicCodeImportTests(TestCase):
    def test_bundle_topic_code_sets_primary_topic(self):
        topic, _created = Topic.objects.get_or_create(
            code="ALG.03.14", defaults={"name": "Рациональные уравнения"})
        payload = bundle(topic_code="ALG.03.14")
        payload["tasks"].append({
            **payload["tasks"][0], "external_id": "1.2.38",
            "topic_code": "NO.SUCH"})
        batch = create_batch_from_bundle(
            payload, user=make_teacher(), title="Партия",
            source_title="Шабунин")
        first, second = batch.drafts.order_by("external_id")
        self.assertEqual(first.topic_id, topic.pk)
        self.assertIn(topic.pk, first.topic_ids)
        self.assertIn("Тема с кодом NO.SUCH не найдена в рубрикаторе",
                      second.warnings)
