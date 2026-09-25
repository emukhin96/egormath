"""Структура нового профиля и сохранность вариантов при загрузке."""
from dataclasses import asdict
import hashlib
from unittest.mock import patch
from django.test import RequestFactory, SimpleTestCase, TestCase
from problems.feoktistov_parser import _answer_markers, _known_answer_work, _unbalanced_math
from problems.forms import TextbookBundleUploadForm
from problems.models import TextbookTaskDraft, Topic
from problems.tests import make_teacher
from problems.textbook_import import create_batch_from_bundle, commit_batch
from problems.textbook_parser import bundle_from_text
from worksheets.models import Collection
from problems.views import _section_nav_rows

SOURCE = r'''
\section*{САМОСТОЯТЕЛЬНАЯ РАБОТА № 1 Свойства функций}
\section*{ОСНОВНЫЕ СВЕДЕНИЯ}
\begin{itemize}\item[1.] Это теория.\end{itemize}
\section*{Подготовительный вариант}
\begin{enumerate}
\item Найдите число: а) \(1+1\); б) \(2+2\).
\item Докажите утверждение.
\end{enumerate}
\section*{Вариант 1}
\begin{itemize}\item[1.] Найдите сумму \(2+3\).\end{itemize}
\section*{САМОСТОЯТЕЛЬНАЯ РАБОТА № 2 Свойства функций}
Подготовительный вариант
\begin{enumerate}\item Найдите число \(3+3\).\end{enumerate}
\section*{КОНТРОЛЬНЫЕ РАБОТЫ}
\section*{КОНТРОЛЬНАЯ РАБОТА № 1}
\section*{Глава 1. Свойства функций}
\section*{Вариант 1}
\begin{itemize}\item[1.] Найдите число \(4+4\).\end{itemize}
\section*{ТЕСТЫ}
Вводный текст тестов не является условием.
\section*{ТЕСТ 1}
\section*{Функции}
\section*{Вариант 1}
\begin{itemize}
\item[1.] Выберите значение функции.
1) 0; 2) 1; 3) 2; 4) 3.
\end{itemize}
\section*{КОММЕНТАРИЙ ДЛЯ УЧИТЕЛЯ}
\begin{itemize}\item[9.] Служебный комментарий.\end{itemize}
\section*{ОТВЕТЫ}
\section*{Самостоятельная работа № 1}
Подготовительный вариант. 1. а) 2; б) 4.
В ар и ант 1. 1. 5.
\section*{Самостоятельная работа № 2}
Подготовительный вариант. 1. 6.
\section*{Контрольная работа № 1}
Вариант 1. 1. 8.
\begin{table}
\begin{tabular}{llllllll}
\multirow{2}{*}{Т1 Функции} & Вариант 1 & 2 & 4 & 1 & 3 & 2 & 4 \\
 & Вариант 2 & 1 & 4 & 2 & 4 & 3 & 1 \\
\end{tabular}
\end{table}
'''

class FeoktistovParserTests(SimpleTestCase):
    def _three_tasks(self, answers):
        return (r'\section*{САМОСТОЯТЕЛЬНАЯ РАБОТА № 1}'
                '\nВариант 1\n1. Вычислите: а) x; б) y.\n'
                '2. Найдите точку.\n3. Вычислите: а) x; б) y.\n'
                r'\section*{ОТВЕТЫ}\section*{Самостоятельная работа № 1}'
                '\nВариант 1. ' + answers)

    def test_answer_numbers_after_line_break_keep_correct_offsets(self):
        source = self._three_tasks(r'''1. а) \(x\); б) \(y\).\\
2. (6; -3).\\
3. а) \(1\);\\
б) \(2\).''')
        tasks = bundle_from_text('feoktistov', source).tasks
        self.assertEqual(tasks[1].author_answer_latex, '(6; -3)')
        self.assertEqual([s.author_answer_latex for s in tasks[2].subitems], ['$1$', '$2$'])
        self.assertNotIn('(6; -3)', tasks[0].author_answer_latex)
        formula = '1. ' + r'\(\begin{array}{l}x=1\\' + '\n2. y=2' + r'\end{array}\).'
        self.assertEqual([m.external_id for m in _answer_markers(formula, {'1', '2'})], ['1'])

    def test_missing_group_and_damaged_heading_are_reported(self):
        source = SOURCE.replace('В ар и ант 1.', 'В ар и - ант 1.')
        bundle = bundle_from_text('feoktistov', source)
        self.assertIn('sr/01/v1: пустая группа авторских ответов',
                      bundle.diagnostics['feoktistov_structure_issues'])
        self.assertIn('sr/01/v1/001', bundle.diagnostics['feoktistov_missing_answer_ids'])
        previous = next(t for t in bundle.tasks if t.external_id == 'sr/01/prep/001')
        self.assertIn('В ответе остался обломок заголовка варианта', previous.warnings)

    def test_duplicate_answer_group_is_not_overwritten(self):
        source = SOURCE.replace('В ар и ант 1. 1. 5.', 'Вариант 1. 1. 5. Вариант 1. 1. 9.')
        with self.assertRaisesMessage(ValueError, 'Повторная группа ответов: sr/01/v1'):
            bundle_from_text('feoktistov', source)

    def test_known_scan_repairs_are_hash_gated_and_preserve_original(self):
        source = (r'\section*{САМОСТОЯТЕЛЬНАЯ РАБОТА № 17}'
                  '\nВариант 3\n1. Найдите число.\n'
                  r'\section*{ОТВЕТЫ}\section*{Самостоятельная работа № 17}'
                  '\nВ а - риант 3. 1. 7.')
        self.assertEqual(bundle_from_text('feoktistov', source).tasks[0].author_answer_latex, '')
        with patch('problems.feoktistov_parser.SOURCE_SHA256', hashlib.sha256(source.encode()).hexdigest()):
            bundle = bundle_from_text('feoktistov', source)
        self.assertEqual(bundle.tasks[0].author_answer_latex, '7')
        self.assertIn('В а - риант', bundle.diagnostics['feoktistov_original_answer_works']['sr/17'])
        repaired = _known_answer_work('sr', 12, '')
        self.assertFalse(_unbalanced_math(repaired))
        self.assertEqual(repaired.count('\\begin{cases}'), 4)
        source = (r'\section*{САМОСТОЯТЕЛЬНАЯ РАБОТА № 12}'
                  '\nВариант 1\n4. Задайте систему.\n'
                  r'\section*{ОТВЕТЫ}\section*{Самостоятельная работа № 12}'
                  '\n' + repaired)
        answer = bundle_from_text('feoktistov', source).tasks[0].author_answer_latex
        self.assertIn(r'\begin{cases}', answer)
        self.assertIn(r'\end{cases}$', answer)
        self.assertNotIn(r'\right$', answer)

    def test_unmatched_answer_labels_stay_outside_math(self):
        source = self._three_tasks(r'1. а) \(\frac{x}{2}\); б) \(y\); в) \(z\).')
        task = bundle_from_text('feoktistov', source).tasks[0]
        self.assertIn('Не совпали подпункты условия и решения', task.warnings)
        self.assertNotRegex(task.author_answer_latex, r'[а-я]\s*\$(?:\\displaystyle\s*)?\)')
        self.assertIn('а)', task.author_answer_latex)
        self.assertIn(r'\frac{x}{2}', task.author_answer_latex)

    def test_suspect_following_number_inside_math_gets_specific_warning(self):
        source = self._three_tasks(r'1. \(x=1. 2. y=2\).')
        bundle = bundle_from_text('feoktistov', source)
        self.assertIn('В ответе возможны следующие номера: 2', bundle.tasks[0].warnings)
        self.assertEqual(bundle.diagnostics['feoktistov_missing_answers_by_work'], {'sr/01': 2})

    def test_non_variant_navigation_keeps_compact_title(self):
        for path in (['Глава 1', '§ 2', 'Квадратные уравнения'],
                     ['Алгебра', 'Функции', 'Графики']):
            leaf = {'path': path, 'title': path[-1], 'count': 1, 'is_leaf': True, 'token': 'test'}
            row = _section_nav_rows([leaf], RequestFactory().get('/'), '')[0]
            self.assertEqual(row['title'], path[-1])

    def test_local_numbers_theory_and_answer_choices(self):
        bundle = bundle_from_text('feoktistov', SOURCE)
        by_id = {t.external_id: t for t in bundle.tasks}
        self.assertEqual(len(by_id), 6)
        self.assertEqual(by_id['sr/01/v1/001'].author_answer_latex, '5')
        self.assertEqual(by_id['sr/02/prep/001'].author_answer_latex, '6')
        self.assertEqual(by_id['kr/01/v1/001'].author_answer_latex, '8')
        self.assertEqual(by_id['sr/01/prep/002'].author_answer_latex, '')
        self.assertEqual([x.author_answer_latex for x in by_id['sr/01/prep/001'].subitems], ['2', '4'])
        test = by_id['test/01/v1/001']
        self.assertEqual(test.subitems, [])
        self.assertIn('4) 3', test.text_latex)
        self.assertEqual(test.answer_mask, '{{choice: 1|*2|3|4}}')
        for task in bundle.tasks:
            self.assertNotIn('Вводный текст', task.text_latex)
            self.assertNotIn('теория', task.text_latex)
            self.assertNotIn('Служебный', task.text_latex)

    def test_enumerated_options_and_common_graph_are_not_separate_tasks(self):
        source = r'''
\section*{TECT 1}
\section*{Вариант 2}
\begin{figure}\includegraphics{graph}\caption{Рис. 17}\end{figure}
На рисунке 17 изображён график функции. Пользуясь данным рисунком выполните упражнения № 2-5.
2. Найдите область определения.
\begin{enumerate}\item \([0;4]\);\item \([0;8]\);\item \([1;4]\);\item \([-1;4]\).\end{enumerate}
\begin{enumerate}\setcounter{enumi}{2}\item Найдите область значений.\end{enumerate}
1) 1; 2) 2; 3) 3; 4) 4.
\section*{ОТВЕТЫ}
'''
        tasks = bundle_from_text('feoktistov', source).tasks
        self.assertEqual([t.source_number for t in tasks], ['2', '3'])
        for task in tasks:
            self.assertEqual(task.images, ['graph'])
            self.assertEqual(task.subitems, [])
            self.assertIn(r'\taskpic{1}', task.text_latex)
        self.assertIn('4)', tasks[0].text_latex)

    def test_duplicate_task_number_is_rejected(self):
        source = SOURCE.replace('Найдите сумму', r'Первое условие. \item[1.] Найдите сумму')
        with self.assertRaisesMessage(ValueError, 'Повторный номер'):
            bundle_from_text('feoktistov', source)

    def test_choice_labels_inside_math_and_inline_numbers(self):
        source = r'''
\section*{ТЕСТ 2}
\section*{Вариант 1}
1. Найдите значение.
\(1) x+1\);
\(2) x+2\);
з) \(x+3\);
\(4) x+4\).
2. Какое из чисел \(-1;0;1;2\) является корнем уравнения?
\section*{ОТВЕТЫ}
'''
        first, second = bundle_from_text('feoktistov', source).tasks
        self.assertIn(r'1) \( x+1\)', first.text_latex)
        self.assertIn(r'3) \(x+3\)', first.text_latex)
        self.assertIn(r'4) \(2\)', second.text_latex)
        self.assertEqual(first.subitems, [])
        self.assertEqual(second.subitems, [])
        self.assertNotIn('Сверить четыре варианта ответа теста с PDF', first.warnings)

    def test_unbalanced_formula_remains_flagged_for_review(self):
        source = SOURCE.replace(r'\(2+3\)', r'\(2+3')
        task = next(t for t in bundle_from_text('feoktistov', source).tasks
                    if t.external_id == 'sr/01/v1/001')
        self.assertIn('Незакрытые разделители формулы: сверить с PDF', task.warnings)

    def test_unknown_scan_is_not_silently_repaired(self):
        bundle = bundle_from_text('feoktistov', SOURCE)
        self.assertFalse(bundle.diagnostics['feoktistov_known_scan'])
        self.assertEqual(bundle.diagnostics['feoktistov_required_recovered_assets'], [])
        self.assertIn('feoktistov', dict(TextbookBundleUploadForm.PROFILE_CHOICES))

class FeoktistovImportTests(TestCase):
    def test_preparatory_and_numbered_variants_share_work_but_not_task_keys(self):
        user = make_teacher()
        payload = asdict(bundle_from_text('feoktistov', SOURCE))
        batch = create_batch_from_bundle(payload, user=user, title='Проба', source_title='Феоктистов')
        self.assertEqual(batch.drafts.count(), 6)
        self.assertEqual(batch.drafts.get(external_id='test/01/v1/001').answer_mask, '{{choice: 1|*2|3|4}}')
        self.client.force_login(user)
        response = self.client.get(f'/problems/imports/{batch.pk}/')
        self.assertContains(response, 'Самостоятельная работа № 1. Свойства функций › Подготовительный вариант')
        self.assertContains(response, 'Самостоятельная работа № 2. Свойства функций › Подготовительный вариант')
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED, topic=Topic.objects.create(name="Тема проверки"))
        commit_batch(batch, user=user)
        leaf = Collection.objects.get(source=batch.source, locator='key:sr/01')
        rubrics = list(leaf.worksheet.items.exclude(rubric='').values_list('rubric', flat=True))
        self.assertEqual(rubrics, ['Подготовительный вариант', 'Вариант 1'])
        self.assertEqual(leaf.worksheet.items.filter(task__isnull=False).count(), 3)
        self.assertTrue(Collection.objects.filter(source=batch.source, locator='key:sr/02').exists())
        self.assertFalse(Collection.objects.filter(source=batch.source, locator='key:sr/01/prep').exists())
        commit_batch(batch, user=user)
        self.assertEqual(leaf.worksheet.items.filter(task__isnull=False).count(), 3)
