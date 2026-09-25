"""Структура нового профиля и сохранность вариантов при загрузке."""
from dataclasses import asdict
from django.test import SimpleTestCase, TestCase
from problems.forms import TextbookBundleUploadForm
from problems.models import TextbookTaskDraft, Topic
from problems.tests import make_teacher
from problems.textbook_import import create_batch_from_bundle, commit_batch
from problems.textbook_parser import bundle_from_text
from worksheets.models import Collection

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
