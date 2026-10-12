"""Табличная маска «Заполните таблицу»: строки ``| … | … |`` со слотами."""
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from problems.models import Task
from problems.templatetags.task_extras import web_answer
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .checks import (MaskTable, Slot, check_mask, collect_values, filled_text,
                     parse_mask, reference_text, render_fragments)
from .models import Assignment, Submission, SubmissionCheckAttempt

DISTANCES = '''Заполните таблицу.
| № | Прямые | | Расстояние |
|---|---|---|---|
| 1 | $AA_1$ | $DC$ | {{expression: a | positive: a}} |
| 2 | $B_1D$ | $AC$ | {{number: \\frac{\\sqrt{6}}{6}}} |
| 3 | $DK$ | $AC_1$ | {{number: 0}} |'''

POSITIONS = '''| № | Прямая и плоскость | Расположение |
|---|---|---|
| 1 | $DB$ и $AMN$ | {{choice: *А|Б|В|Г}} |
| 2 | $MN$ и $ABC$ | {{choice: А|Б|*В|Г}} |'''


class TableParseTests(SimpleTestCase):
    def test_rows_header_cells_and_slot_order(self):
        spec = parse_mask(DISTANCES)
        self.assertEqual(spec.errors, [])
        self.assertTrue(spec.is_valid)
        intro, table = spec.fragments
        self.assertEqual(intro, 'Заполните таблицу.')
        self.assertIsInstance(table, MaskTable)
        self.assertEqual(table.header, 1)
        self.assertEqual(len(table.rows), 4)
        self.assertEqual(table.rows[0], [['№'], ['Прямые'], [], ['Расстояние']])
        self.assertEqual(table.rows[1][1], ['$AA_1$'])
        self.assertEqual([s.name for s in spec.slots], ['s1', 's2', 's3'])
        self.assertEqual([s.kind for s in spec.slots], ['expression', 'number', 'number'])
        # «|» внутри слота (опция positive) ячейку не делит
        self.assertEqual(spec.slots[0].reference, 'a')

    def test_slots_around_table_numbered_in_reading_order(self):
        spec = parse_mask('Ответ: {{number: 1}}\n|---|---|\n| {{number: 2}} | {{number: 3}} |\nИ ещё {{number: 4}}')
        self.assertEqual([s.reference for s in spec.slots], ['1', '2', '3', '4'])
        self.assertEqual([s.name for s in spec.slots], ['s1', 's2', 's3', 's4'])
        self.assertEqual(spec.fragments[0], 'Ответ: ')
        self.assertIsInstance(spec.fragments[2], MaskTable)
        self.assertEqual(spec.fragments[3], 'И ещё ')

    def test_pipes_in_choice_math_and_escape(self):
        spec = parse_mask('|---|---|---|\n' r'| $|x|$ \| $y$ | {{choice: *А|Б|В|Г}} | {{compare: >}}° |')
        self.assertEqual(spec.errors, [])
        (row,) = spec.fragments[0].rows
        self.assertEqual(row[0], ['$|x|$ | $y$'])
        self.assertEqual(row[1][0].options, ['А', 'Б', 'В', 'Г'])
        # Единица после слота в ячейке относится к нему, как в тексте
        self.assertTrue(row[2][0].degree_unit)
        self.assertEqual(row[2][1], '°')

    def test_all_slot_kinds_work_inside_cells(self):
        spec = parse_mask(
            '|---|\n| {{digits: 234}} | {{decimal: -0,5}} | {{ratio: 1:2}} | {{set: 1; 2}} '
            '| {{pair: (1; 2)}} | {{range: (1;4)}} | {{order: 1|2|3}} | {{yesno: да}} '
            '| {{series: \\pi n}} | {{equation: y=x+5}} |')
        self.assertEqual(spec.errors, [])
        self.assertEqual(len(spec.slots), 10)
        values = {'s1': '234', 's2': '-0,50', 's3': '2:4', 's4': '2;1',
                  's5': '(1;2)', 's6': '1<x<4', 's7': '0|1|2', 's8': 'да',
                  's9': '\\pi k', 's10': 'y-x=5'}
        result, checks = check_mask(spec, values)
        self.assertEqual(checks, {name: 'ok' for name in values})
        self.assertEqual(result, 'ok')

    def test_column_count_and_rule_errors(self):
        self.assertEqual(parse_mask('|---|---|\n| {{number: 1}} | a |\n| {{number: 2}} |').errors,
                         ['таблица: в строке 2 ячеек 1, а в первой — 2'])
        self.assertIn('строка-разделитель',
                      parse_mask('| a |\n|---|\n| {{number: 1}} |\n|---|').errors[0])

    def test_slot_error_inside_cell_reported_with_number(self):
        spec = parse_mask('|---|---|\n| a | {{number: 1}} |\n| b | {{number: abc}} |')
        self.assertFalse(spec.is_valid)
        self.assertEqual(spec.errors, ['слот 2 ({{number: …}}): эталон не разобран как число'])

    def test_table_without_slots_is_not_a_mask(self):
        self.assertEqual(parse_mask('| a | b |\n|---|---|').errors,
                         ['в маске нет ни одного слота {{тип: …}}'])

    def test_blank_line_splits_tables(self):
        spec = parse_mask('|---|\n| {{number: 1}} |\n\n|---|---|\n| {{number: 2}} | {{number: 3}} |')
        self.assertEqual(spec.errors, [])
        self.assertEqual([type(f) for f in spec.fragments], [MaskTable, MaskTable])

    def test_rule_first_line_means_no_header(self):
        spec = parse_mask('|---|---|\n| $AB$ | {{number: 1}} |')
        self.assertEqual(spec.errors, [])
        self.assertEqual(spec.fragments[0].header, 0)
        self.assertEqual(len(spec.fragments[0].rows), 1)

    def test_pipe_lines_without_rule_stay_text(self):
        # Модули по краям строки — не таблица: без |---| разбор как раньше
        for text in ('|x| = {{number: 2}} или |y|',
                     '| {{number: 1}} | {{number: 2}} |',
                     'Ответ:\n|AB| = {{number: 5}} |\n|CD| = {{number: 6}} |'):
            spec = parse_mask(text)
            self.assertEqual(spec.errors, [])
            self.assertFalse(any(isinstance(f, MaskTable) for f in spec.fragments))
            self.assertEqual(reference_text(spec).count('tabular'), 0)
        spec = parse_mask('|x| = {{number: 2}} или |y|')
        self.assertEqual(spec.fragments, ['|x| = ', spec.slots[0], ' или |y|'])

    def test_plain_masks_unchanged(self):
        spec = parse_mask('Ответ: {{number: 10}} см\n|x| = {{number: 3}}')
        self.assertEqual(spec.errors, [])
        self.assertEqual([type(f) for f in spec.fragments], [str, Slot, str, Slot])
        self.assertEqual(spec.fragments[2], ' см\n|x| = ')


class TableCheckAndTextTests(SimpleTestCase):
    def test_check_values_like_plain_slots(self):
        spec = parse_mask(POSITIONS)
        self.assertEqual(check_mask(spec, {'s1': 'А', 's2': 'В'}),
                         ('ok', {'s1': 'ok', 's2': 'ok'}))
        self.assertEqual(check_mask(spec, {'s1': 'А', 's2': 'Б'})[0], 'wrong')
        self.assertEqual(check_mask(spec, {'s1': 'А'})[0], 'unknown')

    def test_collect_values_and_order_inside_table(self):
        spec = parse_mask('|---|---|\n| Порядок | {{order: 1|2|3}} |\n| Число | {{number: 5}} |')
        tokens = spec.slots[0].order_tokens('p7')
        data = {'p7_s1_0': tokens[0], 'p7_s1_1': tokens[1], 'p7_s1_2': tokens[2],
                'p7_s2': ' 5 '}
        values = collect_values(data, 'p7', spec)
        self.assertEqual(values, {'s1': '0|1|2', 's2': '5'})
        self.assertEqual(check_mask(spec, values)[0], 'ok')

    def test_reference_and_filled_text_are_tabular(self):
        spec = parse_mask(POSITIONS)
        reference = reference_text(spec)
        self.assertTrue(reference.startswith('\\begin{tabular}{|l|l|l|}'))
        self.assertIn('1 & $DB$ и $AMN$ & [А] \\\\ \\hline', reference)
        filled = filled_text(spec, {'s2': 'Б'})
        self.assertIn('1 & $DB$ и $AMN$ & ___ \\\\ \\hline', filled)
        self.assertIn('2 & $MN$ и $ABC$ & [Б] \\\\ \\hline', filled)
        spec = parse_mask('Таблица:\n|---|\n| {{number: 1}} |\nКонец')
        self.assertEqual(reference_text(spec),
                         'Таблица:\n\\begin{tabular}{|l|}\n\\hline\n[1] \\\\ \\hline\n'
                         '\\end{tabular}\nКонец')

    def test_tabular_cell_escapes_ampersand_outside_math(self):
        spec = parse_mask('|---|---|---|\n| A & B | $\\begin{matrix}1 & 2\\end{matrix}$ | {{number: 1}} |')
        self.assertIn('A \\& B & $\\begin{matrix}1 & 2\\end{matrix}$ & [1]',
                      reference_text(spec))

    def test_web_answer_renders_tabular_as_table(self):
        html = web_answer(reference_text(parse_mask(DISTANCES)))
        self.assertTrue(html.startswith('Заполните таблицу.<table class="tex-table">'))
        self.assertIn('<td>$DC$</td><td>[$a$]</td>', html)
        self.assertIn('<td>0</td>', html.replace('[0]', '0'))
        self.assertNotIn('hline', html)
        self.assertNotIn('$$', html)

    def test_web_answer_without_tables_unchanged(self):
        from problems.textbook_parser import apply_imported_answer
        from problems.web_tex import map_outside_tables
        for text in ('$x=2$.', 'Ответ: [\\frac{1}{2}] см', '\\{-2;1\\}'):
            self.assertEqual(map_outside_tables(text, apply_imported_answer),
                             apply_imported_answer(text))


class TableTemplateTests(SimpleTestCase):
    def test_editable_table_has_inputs_in_cells(self):
        spec = parse_mask(POSITIONS)
        html = render_to_string('assignments/_mask.html', {
            'fragments': render_fragments(spec, 'task5'), 'editable': True,
            'show_checks': True})
        self.assertIn('<div class="mask-table-wrap"><table class="mask-table"><tr><th>', html)
        self.assertIn('<th><span class="mask-text">Расположение</span></th>', html)
        self.assertIn('<td><span class="mask-slot mask-slot-choice"><select name="task5_s1"', html)
        self.assertIn('name="task5_s2"', html)
        self.assertEqual(html.count('<tr>'), 3)
        self.assertIn('<span class="check-badge" data-check="task5_s1"', html)

    def test_readonly_table_shows_values_and_statuses(self):
        spec = parse_mask(POSITIONS)
        html = render_to_string('assignments/_mask.html', {
            'fragments': render_fragments(spec, 'task5', {'s1': 'А'}, {'s1': 'ok'}),
            'editable': False})
        self.assertIn('<td><span class="mask-slot mask-slot-choice">'
                      '<span class="mask-value" data-status="ok">А</span>', html)
        self.assertIn('<span class="mask-blank">___</span>', html)
        self.assertNotIn('<select', html)


class TableAssignmentFlowTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        worksheet = make_worksheet(self.teacher)
        self.task = Task.objects.create(text_latex='Заполните таблицу.', answer_mask=POSITIONS)
        WorksheetItem.objects.create(worksheet=worksheet, task=self.task, order=1)
        self.assignment = Assignment.objects.create(
            worksheet=worksheet, student=self.student, assigned_by=self.teacher)

    def test_check_saves_values_and_attempt_keeps_table(self):
        self.client.force_login(self.student)
        page = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(page, '<table class="mask-table">')
        self.assertContains(page, f'name="task{self.task.pk}_s2"')
        self.client.post(reverse('check_task', args=[self.assignment.pk, self.task.pk]),
                         {f'task{self.task.pk}_s1': 'А', f'task{self.task.pk}_s2': 'Б'})
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.answer_json, {'s1': 'А', 's2': 'Б'})
        self.assertEqual(submission.check_json, {'s1': 'ok', 's2': 'wrong'})
        self.assertEqual(submission.auto_check, 'wrong')
        self.assertIn('\\begin{tabular}', submission.display_answer)
        target = SubmissionCheckAttempt.objects.get(submission=submission).snapshot['targets'][0]
        table = target['fragments'][0]
        self.assertTrue(table['table'])
        self.assertEqual(table['rows'][1]['cells'][2], [{'kind': 'choice', 'display': 'А'}])
        self.assertTrue(table['rows'][0]['header'])
        self.client.force_login(self.teacher)
        attempts = self.client.get(reverse('task_attempts', args=[self.assignment.pk, self.task.pk]))
        self.assertContains(attempts, '<table class="mask-table">')
        review = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(review, '<table class="mask-table">')
        self.assertContains(review, 'class="mask-value" data-status="wrong">Б<')


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class TableIndependentWorkTests(TestCase):
    def test_attempt_renders_table_and_checks_values(self):
        from independentworks import services as svc
        from independentworks.models import Candidate, Position, Work
        User = get_user_model()
        teacher = User.objects.create_user('teacher')
        Profile.objects.create(user=teacher, role='teacher')
        student = User.objects.create_user('student')
        Profile.objects.create(user=student, teacher=teacher, role='student')
        work = Work.objects.create(owner=teacher, title='Таблицы')
        task = Task.objects.create(text_latex='Заполните таблицу.', answer_mask=POSITIONS)
        Candidate.objects.create(position=Position.objects.create(work=work), task=task)
        run = svc.prepare(work, teacher, [student.pk], self_check=True)
        svc.issue(run.pk)
        attempt = svc.start(run.attempts.get().pk)
        point = attempt.variant.points.get()
        self.client.force_login(student)
        page = self.client.get(reverse('independentworks:attempt', args=[attempt.pk]))
        self.assertContains(page, '<table class="mask-table">')
        self.assertContains(page, f'name="p{point.pk}_s2"')
        response = self.client.post(
            reverse('independentworks:check_answer', args=[attempt.pk, point.pk]),
            {'version': 0, f'p{point.pk}_s1': 'А', f'p{point.pk}_s2': 'В'})
        self.assertTrue(response.json()['ok'])
        answer = attempt.answers.get()
        self.assertEqual(answer.values, {'s1': 'А', 's2': 'В'})
        self.assertEqual(answer.auto_check, 'ok')
        self.assertIn('\\begin{tabular}', svc.answer_display(point, answer))
