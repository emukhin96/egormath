"""Тесты профиля Мерзляка: OCR-фрагменты как в книге, а не идеальный TeX."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .merzlyak_parser import (
    answer_markers, cut_task_body, normalize_degrees, normalize_units,
    parse_merzlyak, prepare_merzlyak_text, wrap_answer_numbers)
from .models import TextbookTaskDraft
from .test_textbook_import import make_teacher
from .textbook_parser import bundle_from_text

FIGURE = r"""
\begin{figure}[h]
\begin{center}
  \includegraphics[alt={},max width=\textwidth]{%s}
\captionsetup{labelformat=empty}
\caption{%s}
\end{center}
\end{figure}
"""


def figure(path, caption):
    return FIGURE % (path, caption)


BOOK = r"""
\section*{§ 1 Синус, косинус, тангенс и котангенс угла от 0° до \(\mathbf{1 8 0}^{\boldsymbol{\circ}}\)}
Теория параграфа. На рисунке 1.1 изображена единичная полуокружность.
""" + figure("uuid-005_1", "Рис. 1.1") + r"""
\begin{itemize}
  \item[1.] Какую полуокружность называют единичной?
\end{itemize}

Упражнения\\
1.1. Чему равен:

\begin{itemize}
  \item[1)] \(\sin \left(180^{\circ}-\alpha\right)\), если \(\sin \alpha=\frac{1}{3}\);
  \item[2)] \(\cos \left(180^{\circ}-\alpha\right)\), если \(\cos \alpha=0,7\)?
\end{itemize}

1.2. Чему равен синус угла, если его косинус равен: 1) 1; 2) 0?\\
1.3. Существует ли угол \(\alpha\), для которого:

\begin{enumerate}
  \item \(\sin \alpha=0,3\);
  \item \(\cos \alpha=1,001\);
\end{enumerate}

\begin{itemize}
  \item[]
  \begin{itemize}
    \item[3)] \(\sin \alpha=2\) ?\\
1.4. В треугольнике \(A B C\) известно, что \(A B=5 \mathrm{~cm}, B C=8 \mathrm{~cm}\), \(\angle B=60^{\circ}\). Найдите сторону \(A C\) (рис. 1.5).
  \end{itemize}
  \item[1.5] (Теорема Стюарта). Докажите равенство.
  \item[] ◇ ◇ ◇
  \item[1.6.] Точки \(A, B, C, D: 1\) ) равны; 2) сонаправлены (см. рисунок 1.6).
\end{itemize}
""" + figure("uuid-007_1", "Рис. 1.5") + r"""
\begin{itemize}
  \item[1.7.] Заполните таблицу.
\end{itemize}

\begin{tabular}[t]{|l|l|}
\hline
Точка & \(a_{3}\) \\
\hline
\(A\) & (-3; 1) \\
\hline
\end{tabular}

\section*{§ 2 Теорема косинусов}
Из первого признака равенства треугольников следует, что две стороны и угол между ними однозначно определяют треугольник.

\section*{Упражнения}
2.1. Стороны треугольника равны 12 см и 20 с м. Найдите наибольший угол треугольника.

2.2. Найдите отрезок \(C D\), если \(A B=6\) см.

Итоги главы 1

Теорема косинусов\\
Квадрат стороны треугольника равен сумме квадратов двух других сторон.

\section*{18.1. Отметим на плоскости точку \(\boldsymbol{O}\). Зададим}
преобразование плоскости. Постройте образы точек \(A\) и \(B\).

\section*{Ответы и указания к упражнениям}
Плава 1. 1.1. 1) \(\frac{1}{3}\); 2) 0,7. 1.2. 1) 0; 2) 1. 1.4. 7 см. Указание. Воспользуйтесь ключевой задачей 1.1. 1.6. 1) \(A B\) и \(D C\); 2) \(A B\) и \(C D\). 1.7. \(x+3 y=13\) и \(9 x-13 y=37.2 .1 .120°\). 2.2. \(2 \sqrt{7}\) см. Указание. Точ-
""" + figure("uuid-276_1", "Рисунок к задаче 2.2") + r"""
ки лежат на одной окружности (см. рисунок).
\section*{Алфавитно-предметный указатель}
Вектор 1.1, 2.1
"""


class MerzlyakParserTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tasks, cls.diagnostics = parse_merzlyak(BOOK)
        cls.by_id = {task.external_id: task for task in cls.tasks}

    def test_finds_tasks_by_paragraph_number_and_builds_chapter_path(self):
        self.assertEqual(
            sorted(self.by_id, key=lambda key: tuple(map(int, key.split('.')))),
            ['1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '2.1', '2.2',
             '18.1'])
        self.assertEqual(self.by_id['2.1'].source_path, [
            'Глава 1. Решение треугольников', '§ 2. Теорема косинусов'])
        self.assertEqual(self.by_id['18.1'].source_path[-1],
                         '§ 18. Преобразование (отображение) фигур')

    def test_theory_and_chapter_summary_do_not_leak_into_tasks(self):
        self.assertNotIn('Из первого признака', self.by_id['1.7'].text_latex)
        self.assertNotIn('Итоги главы', self.by_id['2.2'].text_latex)
        self.assertNotIn('Теорема косинусов', self.by_id['2.2'].text_latex)
        self.assertNotIn('Какую полуокружность', ''.join(
            task.text_latex for task in self.tasks))

    def test_numeric_subitems_from_itemize_inline_and_enumerate(self):
        self.assertEqual([item.label for item in self.by_id['1.1'].subitems],
                         ['1', '2'])
        self.assertEqual([item.label for item in self.by_id['1.2'].subitems],
                         ['1', '2'])
        self.assertEqual(self.by_id['1.2'].subitems[0].text_latex, '1')
        self.assertEqual([item.label for item in self.by_id['1.3'].subitems],
                         ['1', '2', '3'])
        self.assertEqual(self.by_id['1.3'].text_latex,
                         'Существует ли угол \\(\\alpha\\), для которого:')

    def test_label_glued_into_formula_is_recovered(self):
        task = self.by_id['1.6']
        self.assertEqual([item.label for item in task.subitems], ['1', '2'])
        self.assertIn('\\(A, B, C, D\\):', task.text_latex)
        self.assertEqual(task.subitems[0].text_latex, 'равны')

    def test_marker_without_dot_and_task_in_section_heading(self):
        self.assertIn('Теорема Стюарта', self.by_id['1.5'].text_latex)
        self.assertIn('Отметим на плоскости точку \\(O\\)',
                      self.by_id['18.1'].text_latex)
        self.assertIn('Постройте образы', self.by_id['18.1'].text_latex)

    def test_figures_attach_by_caption_not_by_position(self):
        task = self.by_id['1.4']
        self.assertEqual(task.images, ['uuid-005_1'.replace('005_1', '007_1')])
        self.assertIn('(рис. \\taskpic{1})', task.text_latex)
        self.assertNotIn('1.5', task.text_latex)
        self.assertEqual(self.by_id['1.6'].images, [])
        self.assertIn('Не найден рисунок по подписи: 1.6',
                      self.by_id['1.6'].warnings)
        self.assertEqual(self.diagnostics['figures_unreferenced'], ['1.1'])

    def test_answer_figure_by_caption_and_hyphenation(self):
        task = self.by_id['2.2']
        self.assertEqual(task.author_answer_latex, '$2 \\sqrt{7}$ см')
        self.assertEqual(task.images, ['uuid-276_1'])
        self.assertIn('Точки лежат на одной окружности (см. рисунок \\taskpic{1})',
                      task.author_solution_latex)

    def test_answers_with_numeric_labels_go_to_subitems(self):
        task = self.by_id['1.1']
        self.assertEqual(task.subitems[0].author_answer_latex,
                         '$\\displaystyle \\frac{1}{3}$')
        self.assertEqual(task.subitems[1].author_answer_latex, '$0,7$')
        self.assertEqual(task.author_answer_latex, '')
        self.assertEqual(self.by_id['1.2'].subitems[1].author_answer_latex,
                         '$1$')

    def test_reference_to_other_task_is_not_an_answer_boundary(self):
        task = self.by_id['1.4']
        self.assertEqual(task.author_answer_latex, '$7$ см')
        self.assertIn('ключевой задачей 1.1', task.author_solution_latex)
        self.assertEqual(self.by_id['1.1'].author_solution_latex, '')

    def test_units_degrees_and_tables(self):
        self.assertIn('\\(A B=5\\) см, \\(B C=8\\) см', self.by_id['1.4'].text_latex)
        self.assertIn('20 см', self.by_id['2.1'].text_latex)
        text = self.by_id['1.7'].text_latex
        self.assertIn('\\[\\begin{array}{|l|l|}', text)
        self.assertIn('\\text{Точка} & a_{3}', text)
        self.assertNotIn('tabular', text)

    def test_task_number_inside_formula_closes_it(self):
        self.assertEqual(self.by_id['1.7'].author_answer_latex,
                         '$x+3 y=13$ и $9 x-13 y=37$')
        self.assertEqual(self.by_id['2.1'].author_answer_latex,
                         '$120^{\\circ}$')

    def test_diagnostics_list_missing_numbers_and_answer_figures(self):
        self.assertEqual(self.diagnostics['missing_task_ids'], [])
        self.assertEqual(self.diagnostics['answer_figures'], ['2.2'])
        self.assertEqual(self.diagnostics['unique_tasks'], 10)


class MerzlyakHelpersTests(TestCase):
    def test_prepare_flattens_lists_and_junk(self):
        text = prepare_merzlyak_text(
            '\\begin{itemize}\n  \\item[] ◇ ◇ ◇\n  \\item[2.60] (Теорема).'
            '\n  \\item[1)] a\n\\end{itemize}\n\\textbackslash item[5.36.] Б.')
        self.assertIn('\n2.60. (Теорема).', text)
        self.assertIn('\n1) a', text)
        self.assertIn('\n5.36. Б.', text)
        self.assertNotIn('◇', text)

    def test_cut_task_body_stops_at_heading_line_and_section(self):
        body, tail = cut_task_body(
            'Найдите угол.\nОпределение\\\\\nТочки называют…', set())
        self.assertEqual(body, 'Найдите угол.')
        self.assertTrue(tail.startswith('Определение'))
        body, tail = cut_task_body(
            'Докажите, что\n\\[\nS=1 .\n\\]\nНайдите \\(x\\).\n\n'
            'Рассмотрим фиксированную точку \\(O\\) и произвольную точку '
            '\\(X\\). Построим такую точку, что точка является образом. '
            'Говорят, что точка является образом точки при гомотетии с '
            'центром \\(O\\) и коэффициентом два.', set(), 22)
        self.assertIn('Найдите \\(x\\).', body)
        self.assertTrue(tail.startswith('Рассмотрим'))

    def test_answer_markers_are_monotonic_and_skip_references(self):
        text = ('5.30. 1. 5.31. 120°. Указание. Воспользуйтесь ключевой '
                'задачей 5.30. 5.32. 2. 8.1. 3. 5.34. Указание. См. задачу 5.10.')
        allowed = {'5.30', '5.31', '5.32', '5.34', '5.10', '8.1'}
        self.assertEqual(
            [marker.external_id for marker in answer_markers(text, allowed)],
            ['5.30', '5.31', '5.32', '8.1'])

    def test_unit_and_degree_normalizers(self):
        self.assertEqual(normalize_units(r'\(51 \mathrm{~cm}^{2}\), 84 см \({ }^{2}\)'),
                         '\\(51\\) см\\(^{2}\\), 84 см$^{2}$')
        self.assertEqual(normalize_units(r'\(0,2 \mathrm{~m} / \mathrm{c}\)'),
                         '\\(0,2\\) м/с')
        self.assertEqual(normalize_degrees('15°, или 75°'),
                         '$15^{\\circ}$, или $75^{\\circ}$')
        self.assertEqual(normalize_degrees(r'\(60^{\circ}\) или 120°'),
                         '\\(60^{\\circ}\\) или $120^{\\circ}$')

    def test_wrap_answer_numbers(self):
        self.assertEqual(wrap_answer_numbers('13 см, 14 см'), '$13$ см, $14$ см')
        self.assertEqual(wrap_answer_numbers('(1; -4) или (-1; 1)'),
                         '$(1; -4)$ или $(-1; 1)$')
        self.assertEqual(wrap_answer_numbers('1 : 2'), '$1 : 2$')
        self.assertEqual(wrap_answer_numbers('$\\sqrt{2}$ см'), '$\\sqrt{2}$ см')
        self.assertEqual(wrap_answer_numbers('Нет'), 'Нет')


class MerzlyakUploadTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()

    def test_upload_with_merzlyak_profile_creates_drafts(self):
        self.client.login(username='teacher1', password='pass12345')
        upload = SimpleUploadedFile(
            'merzlyak.tex', BOOK.encode(), content_type='text/plain')
        response = self.client.post(reverse('textbook_import_upload'), {
            'title': 'Мерзляк-9', 'source_title': 'Геометрия 9',
            'input_kind': 'answers_end', 'profile': 'merzlyak',
            'tasks_tex': upload,
        })
        self.assertEqual(response.status_code, 302)
        drafts = {draft.external_id: draft
                  for draft in TextbookTaskDraft.objects.all()}
        self.assertEqual(len(drafts), 10)
        self.assertEqual(drafts['1.1'].batch.profile, 'merzlyak')
        self.assertEqual(drafts['1.1'].subitems[1]['author_answer_latex'],
                         '$0,7$')
        self.assertEqual(drafts['1.4'].images, ['uuid-007_1'])
        self.assertIn('\\taskpic{1}', drafts['1.4'].text_latex)

    def test_bundle_from_text_requires_answers_section(self):
        with self.assertRaisesMessage(ValueError, 'Мерзляка'):
            bundle_from_text('merzlyak', '1.1. Задача без ответов.')
