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

    def test_lost_dollar_next_to_prose_heals_only_pair_half(self):
        # Потерян внешний доллар: в формулу уходит половина пары, соседняя
        # фраза остаётся текстом.
        self.assertEqual(heal_split_math_dollars(r"Найдите \left(a$ ;$b\right)"),
                         r"Найдите $\left(a ;b\right)$")
        self.assertEqual(
            heal_split_math_dollars(r"$\left(a$ ; b\right) при $x>0$"),
            r"$\left(a ; b\right)$ при $x>0$")

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

    def test_split_pair_halves_join_into_one_formula(self):
        from .shabunin_parser import _join_split_halves
        self.assertEqual(
            _join_split_halves(
                r"$\displaystyle \left( \pm \frac{7 \pi}{24}+\pi(k+n)\right.$; "
                r"$\displaystyle \left.\pm \frac{\pi}{24}+\pi(n-k)\right)$"),
            r"$\displaystyle \left( \pm \frac{7 \pi}{24}+\pi(k+n) ; "
            r"\pm \frac{\pi}{24}+\pi(n-k)\right)$")
        system = r"$\left\{\begin{array}{l}x=1\end{array}\right.$; $y=2$"
        self.assertEqual(_join_split_halves(system), system)

    def test_quad_separated_answers_become_separate_formulas(self):
        from .shabunin_parser import _split_quad_list
        self.assertEqual(
            _split_quad_list(
                r"$\displaystyle \left(\frac{2}{9} ; \frac{10}{9}\right), "
                r"\quad\left(-\frac{5}{49} ; 1\right), \quad k, n \in \mathbb{Z}$"),
            r"$\displaystyle \left(\frac{2}{9} ; \frac{10}{9}\right)$, "
            r"$\displaystyle \left(-\frac{5}{49} ; 1\right)$, $k, n \in \mathbb{Z}$")
        # Внутри скобок множества и систем «\quad» — часть формулы.
        for value in (r"$\{1, \quad 2\}$",
                      r"$\left\{\begin{array}{l}x=1, \quad y=2\end{array}\right.$",
                      r"$$A(x), \quad B(x)$$"):
            self.assertEqual(_split_quad_list(value), value)

    def test_list_punct_inside_subitem_system_is_removed(self):
        from .shabunin_parser import _strip_system_tail_punct
        self.assertEqual(
            _strip_system_tail_punct(
                r"$\left\{\begin{array}{l}y \geqslant|x|-1, \\ y \leqslant 3 ;\end{array}\right.$"),
            r"$\left\{\begin{array}{l}y \geqslant|x|-1, \\ y \leqslant 3\end{array}\right.$")
        self.assertEqual(
            _strip_system_tail_punct(
                r"$\left\{\begin{array}{l}2^{x}=32, \\ x+y=5 \text {. }\end{array}\right.$"),
            r"$\left\{\begin{array}{l}2^{x}=32, \\ x+y=5\end{array}\right.$")
        # Законченное предложение сохраняет точку, как strip_subitem_punct.
        sentence = (r"Найти $f(1)$, если $f(x)=\left\{\begin{array}{l}x, & x<2, \\ "
                    r"1, & x \geqslant 2 .\end{array}\right.$")
        self.assertEqual(_strip_system_tail_punct(sentence), sentence)

    def test_prose_inside_formula_moves_out(self):
        from .shabunin_parser import _unwrap_math_prose
        self.assertEqual(
            _unwrap_math_prose(
                "Доказать справедливость неравенства\n$$\n\\ln ^{2} x>\\ln (x-1) "
                "\\ln (x+1) \\text { при } x>2 \\text {. }\n$$"),
            "Доказать справедливость неравенства\n$\\ln ^{2} x>\\ln (x-1) "
            "\\ln (x+1)$ при $x>2$.")
        self.assertEqual(
            _unwrap_math_prose(
                r"$A \equiv\left\{\text { Число } 2^{222}-1 \text { делится на } 15\right\}$"),
            r"$A \equiv\{$Число $2^{222}-1$ делится на $15\}$")
        self.assertEqual(
            _unwrap_math_prose(
                r"$x^{2}+\frac{2}{y-3}, \text { если }-2 \leqslant x \text { и } y \leqslant 2,9 .$"),
            r"$x^{2}+\frac{2}{y-3}$, если $-2 \leqslant x$ и $y \leqslant 2,9$.")
        # Текст как часть формулы остаётся: кусочная функция, индекс, имя.
        for value in (
                r"$y=\left\{\begin{aligned}4 x, & \text { если } x>-1\end{aligned}\right.$",
                r"$f_{\text {наим }}=-3$", r"$\operatorname{НОД}(a, b)$",
                r"$x \text {, } y$"):
            self.assertEqual(_unwrap_math_prose(value), value)

    def test_parameter_tasks_get_site_tag(self):
        from types import SimpleNamespace
        from .shabunin_parser import PARAMETER_TAG, _tag_parameter_task
        from .oge_metadata import PARAMETER_TAG as SITE_TAG
        self.assertEqual(PARAMETER_TAG, SITE_TAG)

        def tags(text):
            task = SimpleNamespace(text_latex=text, subitems=[], tags=[])
            _tag_parameter_task(task)
            return task.tags

        for text in ("Найти все значения $a$, при которых уравнение имеет корень.",
                     "При каких значениях параметра $b$ система совместна?",
                     "Решить уравнение при всех значениях $a$:",
                     "Сколько корней имеет уравнение в зависимости от $a$?",
                     "Найти все значения $\\lambda$, при которых уравнения имеют общий корень."):
            self.assertEqual(tags(text), [SITE_TAG], text)
        for text in ("При каких значениях $x$ верно неравенство?",
                     "Найти все значения $x$, удовлетворяющие условию.",
                     "Доказать, что при любом натуральном $n$ число делится на 3.",
                     "Доказать, что функция при любых $a$ и $b$ имеет один экстремум.",
                     "Показать, что при каждом значении параметра $C$ функция — решение.",
                     "Определить число корней при указанных значениях параметра $a$:"):
            self.assertEqual(tags(text), [], text)

    def test_sentence_dot_between_formulas_is_not_task_number(self):
        from .templatetags.task_extras import web_answer
        from .textbook_parser import heal_ocr_task_number_labels
        self.assertEqual(apply_imported_answer(r"$y=1$. $z=2$"), r"$y=1$. $z=2$")
        self.assertNotIn("$$", str(web_answer(
            r"$\displaystyle y=x+1$. $D(y)=\mathbb{R}$. Функция возрастает на $(0;1)$")))
        # Номер следующей задачи OCR вне формулы по-прежнему отделяется.
        self.assertEqual(heal_ocr_task_number_labels(r"$(1;2)$ 5$. (-3;1)"),
                         r"$(1;2)$ 5. (-3;1)")

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
