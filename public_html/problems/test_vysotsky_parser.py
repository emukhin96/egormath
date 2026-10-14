"""Тесты профиля Высоцкого: OCR-фрагменты как в книге, а не идеальный TeX."""

from django.test import SimpleTestCase, TestCase

from .vysotsky_parser import (
    parse_vysotsky, renumber_lists, strip_watermarks,
    task_markers, variant_zones)


BOOK = r"""
\section*{Раздел I}
\section*{Случайные события}
\section*{§1. Классические случайные эксперименты с монетами и игральными костями}
Пояснение. Теория параграфа: при двукратном бросании кости элементарных событий \(6 \cdot 6=36\).

\section*{Задачи для работы в классе}
\begin{enumerate}
  \item Симметричную монету бросили два раза.\\
a) Сколько элементарных исходов в этом эксперименте?\\
б) Выпишите исходы, благоприятствующие событию «выпал хотя бы один орёл».
\end{enumerate}

Пример решения. Обозначим орла буквой О. а) Исходов четыре: ОО, ОР, РО и РР; б) благоприятствуют три исхода.

\begin{enumerate}
  \setcounter{enumi}{1}
  \item Симметричную монету бросили три раза. Найдите вероятность события \(A=\{\) первые два броска окончились одинаково \(\}\).
\end{enumerate}

Пример решения. Всего элементарных событий \(N=8\), поэтому \(\mathrm{P}(A)=0,5\).\\
3.*. Правильную игральную кость бросают дважды. Как результат, полученный в п. а), связан с п. б)?\\
a) Найдите вероятность события «сумма равна 7»;\\
B) найдите вероятность события «сумма равна 8».\\
Результаты округлите до тысячных.

\section*{Задания для домашней работы}
\begin{enumerate}
  \setcounter{enumi}{3}
  \item Симметричную монету бросили два раза. Найдите вероятность события «орёл выпал дважды». AOdV/Gns8v48cw==
\end{enumerate}

\section*{Карточки для индивидуальной работы}
Первый номер в карточке указывает параграф.

1

\begin{enumerate}
  \item Симметричную монету бросили 3 раза. Какое событие вероятнее?\\
2*. Правильную игральную кость бросают дважды. Найдите вероятность события «наибольшее равно 5».
\end{enumerate}

\section*{2}
\begin{enumerate}
  \item Симметричную монету бросили 3 раза. Найдите вероятность события «не все одинаковы».\\
2*. Правильную игральную кость бросают дважды. Какая сумма наиболее вероятна?
\end{enumerate}

\section*{Самостоятельные работы}
Вторая цифра - номер варианта.

1

\begin{enumerate}
  \item Покупатель выбирает лампочку. Найдите вероятность того, что она исправна.
\end{enumerate}

2

\begin{enumerate}
  \item Покупатель выбирает батарейку. Найдите вероятность того, что она исправна.
\end{enumerate}

\section*{Контрольные работы }
\section*{КІ.1. «Случайные события» \\
 Вариант 1 (Базовый уровень)}
\begin{enumerate}
  \item Симметричную монету бросили 3 раза. Найдите вероятность того, что орёл выпал дважды.
\end{enumerate}

\section*{Справочник}
Термины.

\section*{Ответы}
1. а) четыре: ОО, ОР, РО и РР; б) ОО, ОР и РО.

2. 0,5.

3. а) \(\frac{1}{6}\); б) \(\frac{5}{36}\).

4. 0,25.

\section*{Индивидуальные карточки}
И1.1. 1. \(A\). 2. 0,25. И1.2. 1. 0,75. 2. 7.

\section*{Самостоятельные работы}
С1.1. 1. 0,95. С1.2. 1. 0,92.

\section*{Контрольные работы}
КI.1. 1. 0,375.

\section*{Содержание}
"""


class VysotskyParserTests(SimpleTestCase):
    def parse(self):
        tasks, diagnostics = parse_vysotsky(BOOK)
        return {task.external_id: task for task in tasks}, diagnostics

    def test_paragraph_tasks_examples_and_answers(self):
        tasks, diagnostics = self.parse()
        self.assertEqual([k for k in tasks if "/" not in k], ["1", "2", "3", "4"])
        first = tasks["1"]
        self.assertEqual([item.label for item in first.subitems], ["а", "б"])
        self.assertIn("четыре", first.subitems[0].author_answer_latex)
        self.assertEqual(first.source_path[-1], "Задачи для работы в классе")
        self.assertEqual(first.topic_code, "STA.03.03")
        self.assertEqual(first.grade_band_codes, ["GRADE_8", "GRADE_9"])
        # «Пример решения» после списка — разбор задачи 2, ответ — из раздела ответов.
        self.assertTrue(tasks["2"].author_solution_latex.startswith("Пример решения"))
        self.assertEqual(tasks["2"].author_answer_latex, "$0,5$")
        self.assertEqual(tasks["4"].source_path[-1], "Задания для домашней работы")
        self.assertNotIn("AOdV", tasks["4"].text_latex)
        self.assertNotIn("Пояснение", " ".join(t.text_latex for t in tasks.values()))
        self.assertIn("2", diagnostics["worked_examples"])

    def test_star_label_guard_and_common_tail(self):
        tasks, diagnostics = self.parse()
        task = tasks["3"]
        self.assertEqual(task.stars, 1)
        # «в п. а)» — ссылка, а не пункт; латинская «B)» — пункт «в)».
        self.assertIn("в п. а)", task.text_latex)
        self.assertEqual([item.label for item in task.subitems], ["а", "в"])
        self.assertIn("Результаты округлите до тысячных", task.text_latex)
        self.assertNotIn("округлите", task.subitems[-1].text_latex)
        self.assertIn("3", diagnostics["lifted_tails"])

    def test_cards_works_and_tests_keys(self):
        tasks, diagnostics = self.parse()
        self.assertIn("И1.1/1", tasks)
        self.assertEqual(tasks["И1.1/2"].stars, 1)
        self.assertEqual(tasks["И1.2/2"].author_answer_latex, "$7$")
        self.assertEqual(tasks["С1.2/1"].author_answer_latex, "$0,92$")
        self.assertEqual(tasks["КI.1/1"].author_answer_latex, "$0,375$")
        self.assertEqual(tasks["КI.1/1"].topic_code, "STA.03.03")
        self.assertEqual(tasks["С1.1/1"].source_path, ["Самостоятельные работы", "С1.1"])
        self.assertEqual(diagnostics["variant_series"]["И"]["mismatched"], [])


class VysotskyOcrTests(SimpleTestCase):
    def test_answer_items_follow_inline_numbers(self):
        # Mathpix считает \item подряд, а в строке книги два номера.
        text = ("\\begin{enumerate}\n\\setcounter{enumi}{185}\n"
                "\\item а) 0,1. 187. а) 0,21.\n\\item а) 0,1024.\n\\end{enumerate}")
        flat = renumber_lists(text)
        self.assertIn("\n186. а) 0,1. 187.", flat)
        self.assertIn("\n188. а) 0,1024.", flat)

    def test_paragraph_number_in_heading_is_not_a_task(self):
        flat = renumber_lists("\\section*{§1. Монеты}\n\\begin{enumerate}\n\\item Текст\n\\end{enumerate}")
        self.assertIn("\n1. Текст", flat)

    def test_star_after_dot(self):
        markers = task_markers("\n179.*. Катя.\n180. Монета.\n", 179, 180)
        self.assertEqual([(m.external_id, m.kind) for m in markers],
                         [("179", "star"), ("180", "")])

    def test_variant_labels(self):
        zone = "1\n\n1. A\n}\\section*{2}\n1. B\n\n1 1. C\n3\\\\\n1. D"
        self.assertEqual([value for value, _s, _e in variant_zones(zone)], [1, 2, 1, 3])

    def test_watermark_inside_formula(self):
        self.assertEqual(strip_watermarks("Текст AOdV/Gns8v48cw== дальше"), "Текст  дальше")
        self.assertNotIn("aod", strip_watermarks("б) 0,5 aodvncissufaciv==").lower())


class VysotskyCommitTests(TestCase):
    def test_commit_links_work_variants_as_analogs(self):
        from dataclasses import asdict
        from independentworks.models import Family
        from problems.forms import TextbookBundleUploadForm
        from problems.models import TextbookTaskDraft, Topic
        from problems.tests import make_teacher
        from problems.textbook_import import commit_batch, create_batch_from_bundle
        from problems.textbook_parser import bundle_from_text

        self.assertIn('vysotsky', dict(TextbookBundleUploadForm.PROFILE_CHOICES))
        user = make_teacher()
        payload = asdict(bundle_from_text('vysotsky', BOOK))
        batch = create_batch_from_bundle(payload, user=user, title='Проба', source_title='Высоцкий')
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED,
                            topic=Topic.objects.create(name='Тема проверки'))
        # Разбор примера — единый текст к задаче: при создании партии его
        # не режут по пунктам.
        first = batch.drafts.get(external_id='1')
        self.assertIn('Обозначим орла', first.author_solution_latex)
        self.assertIn('благоприятствуют три исхода', first.author_solution_latex)
        self.assertIn('четыре', first.subitems[0]['author_answer_latex'])
        result = commit_batch(batch, user=user)
        self.assertEqual(result['analog_families'], 1)
        self.assertEqual(result['analog_members'], 2)
        # Повторная загрузка ничего не меняет — и результат пустой, чтобы
        # раздел показал «Изменений нет».
        again = commit_batch(batch, user=user)
        self.assertFalse(any(again.values()), again)
        family = Family.objects.get()
        texts = sorted(task.text_latex for task in family.tasks.all())
        self.assertEqual(len(texts), 2)
        self.assertIn('батарейку', texts[0] + texts[1])
        # Карточки не связываются: задачи вариантов карточки разные.
        self.assertEqual(Family.objects.count(), 1)


class VysotskyLayoutTests(SimpleTestCase):
    def test_inline_picture_glues_broken_word(self):
        from .vysotsky_parser import lift_inline_pictures
        text = ("На рисунке изображено дере-\\\\\n\\includegraphics[max width=\\textwidth]{uuid-040_1}\\\\\n"
                "во некоторого эксперимента.\\\\\nа) Найдите.")
        fixed = lift_inline_pictures(text)
        self.assertIn("изображено дерево некоторого эксперимента.\\\\\n\\includegraphics", fixed)

    def test_picture_from_last_subitem_goes_to_stem(self):
        from .textbook_parser import SubitemDraft, TaskDraft
        from .vysotsky_parser import lift_stem_pictures
        task = TaskDraft("1", "1", [], "", "", "", "Схема дорожек показана на рисунке.",
                         subitems=[SubitemDraft("а", "к кафе"),
                                   SubitemDraft("б", "к пруду.\\\\\n\\taskpic{1}")])
        self.assertTrue(lift_stem_pictures(task))
        self.assertTrue(task.text_latex.endswith("\\taskpic{1}"))
        self.assertEqual(task.subitems[1].text_latex, "к пруду.")

    def test_footnote_goes_to_marked_task(self):
        from .textbook_parser import Marker
        from .vysotsky_parser import attach_footnotes, build_task
        pairs = [(Marker(0, 1, "93"), "Сумки.\\({ }^{1}\\)\n"),
                 (Marker(2, 3, "94"), "Диаграмма.\n\\footnotetext{\\({ }^{1}\\) Обратите внимание.\n}\n")]
        (m93, b93), (m94, b94) = attach_footnotes(pairs)
        self.assertIn("Обратите", b93)
        self.assertNotIn("Обратите", b94)
        task = build_task(m93, b93, ["§"])
        self.assertEqual(task.author_solution_latex, "Примечание. Обратите внимание.")
        self.assertNotIn("{ }^{1}", task.text_latex)


class VysotskyPercentTests(SimpleTestCase):
    def test_bare_percent_is_escaped(self):
        from .textbook_parser import SubitemDraft, TaskDraft
        from .vysotsky_parser import _finish_fields
        task = TaskDraft("1", "1", [], "", "", "", "Стрелок (60 % попаданий), уже 10\\%.",
                         subitems=[SubitemDraft("а", "x", author_answer_latex="10,9 %")])
        _finish_fields(task)
        self.assertIn("60 \\% попаданий", task.text_latex)
        self.assertIn("10\\%", task.text_latex)
        self.assertNotIn("\\\\%", task.text_latex)
        self.assertIn("\\%", task.subitems[0].author_answer_latex)


class VysotskyIncompleteBookTests(SimpleTestCase):
    def test_missing_section_is_import_error(self):
        broken = BOOK.replace("\\section*{Справочник}", "\\section*{Термины}")
        with self.assertRaisesRegex(ValueError, "«Справочник»"):
            parse_vysotsky(broken)
