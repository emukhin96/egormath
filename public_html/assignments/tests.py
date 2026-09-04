import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from problems.models import Task, TaskSubitem
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet

from .check_answer import check_answer, check_interval_fields
from .models import (Assignment, Review, Submission, SubmissionPart,
                     SubmissionPhoto)


def make_assignment(teacher, student, **kwargs):
    worksheet = make_worksheet(teacher)
    return Assignment.objects.create(
        worksheet=worksheet, student=student, assigned_by=teacher, **kwargs)


def fake_photo(name='photo.png', size=(2400, 1800)):
    buf = io.BytesIO()
    Image.new('RGB', size, color=(200, 100, 50)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class AssignFlowTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher)

    def test_assign_worksheet(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(
            reverse('assign_worksheet', args=[self.worksheet.pk]),
            {'students': [self.student.pk], 'grade_scale': 'words'})
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertTrue(Assignment.objects.filter(
            worksheet=self.worksheet, student=self.student).exists())

    def test_cannot_assign_foreign_student(self):
        other_teacher = make_teacher('teacher2')
        foreign_student = make_student(other_teacher, 'student2')
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(
            reverse('assign_worksheet', args=[self.worksheet.pk]),
            {'students': [foreign_student.pk], 'grade_scale': 'words'})
        self.assertFalse(Assignment.objects.filter(
            student=foreign_student).exists())


@override_settings(MEDIA_ROOT='/tmp/egormath-test-media')
class StudentAnswerTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.assignment = make_assignment(self.teacher, self.student)
        self.tasks = [item.task for item in
                      self.assignment.worksheet.ordered_items()]
        self.client.login(username='student1', password='pass12345')

    def test_hidden_items_excluded_for_student(self):
        # Скрытая задача не видна на странице задания и не принимает ответ
        item = self.assignment.worksheet.items.order_by('order').first()
        self.assignment.hidden_items.add(item)
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        rows = response.context['rows']
        self.assertNotIn(item.task_id, [r['task'].pk for r in rows if r['task']])
        # Нумерация пересчитана: оставшаяся задача — №1
        self.assertEqual([r['number'] for r in rows if r['task']], [1])
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{item.task_id}_text': 'подсмотрел'})
        self.assertFalse(Submission.objects.filter(
            assignment=self.assignment, task=item.task).exists())

    def test_hidden_item_blocks_photo_and_submit(self):
        hidden = self.assignment.worksheet.items.order_by('order').first()
        visible = self.assignment.worksheet.items.order_by('order').last()
        self.assignment.hidden_items.add(hidden)
        response = self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, hidden.task_id]),
            {'photos': fake_photo()})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Submission.objects.filter(
            assignment=self.assignment, task=hidden.task).exists())
        self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]))
        self.assertFalse(Submission.objects.filter(
            assignment=self.assignment, task=hidden.task).exists())
        self.assertTrue(Submission.objects.filter(
            assignment=self.assignment, task=visible.task).exists())

    def test_save_answers_and_submit(self):
        task = self.tasks[0]
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': 'x = 2'})
        self.assertRedirects(
            response, reverse('assignment_detail', args=[self.assignment.pk]))
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        self.assertEqual(submission.answer_text, 'x = 2')

        response = self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        # Ответы созданы для всех задач
        self.assertEqual(self.assignment.submissions.count(), len(self.tasks))

        # После отправки редактирование запрещено
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': 'меняю ответ'})
        self.assertEqual(response.status_code, 403)

    def test_submit_without_draft_keeps_answers(self):
        """«Отправить» без предварительного «Сохранить» — ответы не теряются."""
        task = self.tasks[0]
        self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]),
            {f'task{task.pk}_text': 'ответ без черновика'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        self.assertEqual(submission.answer_text, 'ответ без черновика')

    def test_submit_without_draft_keeps_subitem_answers(self):
        item = self.assignment.worksheet.ordered_items()[0]
        task = item.task
        s1 = TaskSubitem.objects.create(task=task, order=10, text_latex='$1+1$')
        self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]),
            {f'task{task.pk}_sub{s1.pk}_text': 'два'})
        part = SubmissionPart.objects.get(subitem=s1)
        self.assertEqual(part.answer_text, 'два')

    def test_photo_actions_keep_unsaved_text(self):
        """Загрузка и удаление фото сохраняют присланные поля ответов."""
        task = self.tasks[0]
        self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, task.pk]),
            {'photos': fake_photo(), f'task{task.pk}_text': 'с фото'})
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        self.assertEqual(submission.answer_text, 'с фото')
        photo = SubmissionPhoto.objects.get()
        self.client.post(
            reverse('delete_photo', args=[self.assignment.pk, photo.pk]),
            {f'task{task.pk}_text': 'после удаления фото'})
        submission.refresh_from_db()
        self.assertEqual(submission.answer_text, 'после удаления фото')
        self.assertFalse(SubmissionPhoto.objects.exists())

    def test_post_without_answer_fields_does_not_clear(self):
        """POST без полей ответа (форма фото) не затирает сохранённое."""
        task = self.tasks[0]
        Submission.objects.create(
            assignment=self.assignment, task=task, answer_text='было')
        self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, task.pk]),
            {'photos': fake_photo()})
        self.assertEqual(
            Submission.objects.get(task=task).answer_text, 'было')
        # А явно присланная пустая строка — это осознанная очистка
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': ''})
        self.assertEqual(Submission.objects.get(task=task).answer_text, '')

    def test_save_answers_xhr_returns_json(self):
        task = self.tasks[0]
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': 'x = 3'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(
            Submission.objects.get(task=task).answer_text, 'x = 3')
        # После отправки автосохранение получает JSON-отказ, а не HTML 403
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': 'поздно'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assertEqual(
            Submission.objects.get(task=task).answer_text, 'x = 3')

    def test_assignment_form_has_autosave(self):
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'data-autosave="change"')

    def test_progress_counts_answers_and_photos(self):
        """Сайдбар: «отвечено N из M» учитывает текст, подпункты и фото."""
        t1, t2 = self.tasks
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertEqual(response.context['task_count'], 2)
        self.assertEqual(response.context['answered_count'], 0)
        self.assertEqual(response.context['unanswered_numbers'], [1, 2])

        Submission.objects.create(
            assignment=self.assignment, task=t1, answer_text='x = 1')
        self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, t2.pk]),
            {'photos': fake_photo()})
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertEqual(response.context['answered_count'], 2)
        self.assertContains(response, '2 из 2')

    def test_overdue_badge(self):
        from datetime import timedelta

        from django.utils import timezone
        self.assignment.due_at = timezone.now() - timedelta(days=1)
        self.assignment.save()
        self.assertTrue(self.assignment.is_overdue)
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'просрочено')
        # Просрочка не блокирует сдачу
        self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        self.assertFalse(self.assignment.is_overdue)

    def test_dashboard_groups_by_status(self):
        submitted = make_assignment(self.teacher, self.student,
                                    status=Assignment.STATUS_SUBMITTED)
        reviewed = make_assignment(self.teacher, self.student,
                                   status=Assignment.STATUS_REVIEWED)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['todo'], [self.assignment])
        self.assertEqual(response.context['submitted'], [submitted])
        self.assertEqual(response.context['reviewed'], [reviewed])
        self.assertEqual(response.context['current'], self.assignment)
        self.assertContains(response, 'На проверке')
        self.assertContains(response, 'Проверено')

    def test_formula_answer_wrapped_and_rendered(self):
        """Тип «формула»: голый LaTeX из math-field хранится как $…$,
        редактору отдаётся без $, учителю рендерится, длина не ограничена."""
        task = self.tasks[0]
        task.answer_type = Task.ANSWER_FORMULA
        task.save()
        long_latex = r'\left(-\infty;\ 3\right]\cup\left[5;\ +\infty\right)' * 3
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': long_latex})
        submission = Submission.objects.get(task=task)
        self.assertEqual(submission.answer_text, f'${long_latex}$')
        self.assertEqual(submission.formula_latex, long_latex)
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, '<math-field')
        self.assertContains(response, f'name="task{task.pk}_text"')
        self.assertContains(response, 'formula-dialog')
        # Уже обёрнутое не оборачивается второй раз
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': '$x=1$'})
        self.assertEqual(Submission.objects.get(task=task).answer_text, '$x=1$')
        # Пустая формула — пустой ответ
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_text': ''})
        self.assertEqual(Submission.objects.get(task=task).answer_text, '')

    def test_long_number_and_interval_fit(self):
        task = self.tasks[0]
        task.answer_type = Task.ANSWER_INTERVAL
        task.save()
        long_value = r'\left(-\infty;\ 3\right]' * 4
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_low': long_value, f'task{task.pk}_high': long_value})
        submission = Submission.objects.get(task=task)
        self.assertEqual(submission.interval_low, long_value)
        self.assertGreater(len(submission.interval_high), 64)

    def test_text_answer_has_formula_button_and_readonly_render(self):
        task = self.tasks[0]
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'data-formula-insert')
        self.assertContains(response, 'mathlive')
        Submission.objects.create(
            assignment=self.assignment, task=task, answer_text=r'нет решений при $a<0$')
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, 'mathlive')
        self.assertContains(response, 'answer-readonly')
        self.assertContains(response, 'нет решений при $a&lt;0$')

    def test_save_subitem_answers(self):
        """У задачи с подпунктами ответы сохраняются отдельно (SubmissionPart)."""
        item = self.assignment.worksheet.ordered_items()[0]
        task = item.task
        task.answer_type = Task.ANSWER_NUMBER
        task.save()
        s1 = TaskSubitem.objects.create(task=task, order=10, text_latex='$1+1$')
        s2 = TaskSubitem.objects.create(task=task, order=20, text_latex='$2+2$')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]), {
                f'task{task.pk}_sub{s1.pk}_number': '2',
                f'task{task.pk}_sub{s2.pk}_number': '4',
            })
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        parts = {p.subitem_id: p for p in submission.parts.all()}
        self.assertEqual(parts[s1.pk].answer_number, '2')
        self.assertEqual(parts[s2.pk].answer_number, '4')
        # Страница задания показывает ответы по подпунктам
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, f'task{task.pk}_sub{s1.pk}_number')

    def test_photo_upload_compression(self):
        task = self.tasks[0]
        response = self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, task.pk]),
            {'photos': fake_photo()})
        self.assertRedirects(
            response, reverse('assignment_detail', args=[self.assignment.pk]))
        photo = SubmissionPhoto.objects.get()
        img = Image.open(photo.image.open('rb'))
        self.assertLessEqual(max(img.size), 1600)
        self.assertEqual(img.format, 'JPEG')

    def test_photo_permissions(self):
        task = self.tasks[0]
        self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, task.pk]),
            {'photos': fake_photo()})
        photo = SubmissionPhoto.objects.get()
        url = reverse('photo_file', args=[photo.pk])

        # Сам ученик видит
        self.assertEqual(self.client.get(url).status_code, 200)
        # Его учитель видит
        self.client.login(username='teacher1', password='pass12345')
        self.assertEqual(self.client.get(url).status_code, 200)
        # Чужой учитель не видит
        make_teacher('teacher2')
        self.client.login(username='teacher2', password='pass12345')
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_foreign_student_cannot_open(self):
        other = make_student(self.teacher, 'student2')
        self.client.login(username='student2', password='pass12345')
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 404)


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.assignment = make_assignment(self.teacher, self.student)
        self.task = self.assignment.worksheet.ordered_items()[0].task
        # Ученик отвечает и отправляет
        self.client.login(username='student1', password='pass12345')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{self.task.pk}_text': 'x = 2'})
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        self.client.login(username='teacher1', password='pass12345')

    def test_review_and_complete(self):
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        response = self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{submission.pk}_grade': 'good',
                f'sub{submission.pk}_comment': 'Верно, но оформи решение.',
                'action': 'complete',
            })
        self.assertRedirects(response, reverse('dashboard'))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_REVIEWED)
        review = Review.objects.get(submission=submission)
        self.assertEqual(review.grade_word, 'good')
        self.assertEqual(review.display_grade, 'Хорошо')

        # Ученик видит комментарий
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'Верно, но оформи решение.')
        self.assertContains(response, 'Хорошо')

    def test_review_renders_student_answer_as_math(self):
        """Ответ ученика и эталон проходят web_answer: голый TeX — в $…$,
        HTML — экранирован."""
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        submission.answer_text = r'\{-2;1\}'
        submission.save()
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, r'$\{-2;1\}$')
        self.assertEqual(response.context['answered_count'], 1)

        submission.answer_text = '<b>x</b>'
        submission.save()
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, '&lt;b&gt;x&lt;/b&gt;')
        self.assertNotContains(response, '<b>x</b>')

    def test_return_for_rework(self):
        response = self.client.post(
            reverse('save_review', args=[self.assignment.pk]),
            {'action': 'return'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_RETURNED)
        # Ученик снова может редактировать
        self.client.login(username='student1', password='pass12345')
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{self.task.pk}_text': 'исправленный ответ'})
        self.assertEqual(response.status_code, 302)

    def test_points_scale(self):
        self.assignment.grade_scale = Assignment.SCALE_POINTS
        self.assignment.save()
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{submission.pk}_points': '7,5',
                'action': 'save',
            })
        review = Review.objects.get(submission=submission)
        self.assertEqual(float(review.grade_points), 7.5)

    def test_save_review_keeps_hidden_task_review(self):
        # Скрытая после проверки задача пропадает из формы, но её отзыв
        # не должен удаляться при сохранении остальных оценок
        hidden_item = self.assignment.worksheet.items.order_by('order').first()
        visible_item = self.assignment.worksheet.items.order_by('order').last()
        hidden_sub = Submission.objects.get(
            assignment=self.assignment, task=hidden_item.task)
        visible_sub, _ = Submission.objects.get_or_create(
            assignment=self.assignment, task=visible_item.task)
        Review.objects.create(
            submission=hidden_sub, grade_word='good', reviewer=self.teacher)
        self.assignment.hidden_items.add(hidden_item)
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{visible_sub.pk}_grade': 'medium',
                'action': 'save',
            })
        self.assertTrue(Review.objects.filter(
            submission=hidden_sub, grade_word='good').exists())
        self.assertEqual(
            Review.objects.get(submission=visible_sub).grade_word, 'medium')

    def test_save_review_when_only_one_copy_hidden(self):
        # Одна задача дважды в листке: скрыт только один элемент —
        # оценку по общему Submission всё ещё можно сохранить
        item = self.assignment.worksheet.items.order_by('order').first()
        WorksheetItem.objects.create(
            worksheet=self.assignment.worksheet, task=item.task, order=90)
        self.assignment.hidden_items.add(item)
        submission = Submission.objects.get(
            assignment=self.assignment, task=item.task)
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{submission.pk}_grade': 'poor',
                'action': 'save',
            })
        self.assertEqual(
            Review.objects.get(submission=submission).grade_word, 'poor')

    def test_foreign_teacher_cannot_review(self):
        make_teacher('teacher2')
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 404)


class AnswerCheckTests(SimpleTestCase):
    """Сверка ответов: школьная запись, промежутки, множества, sympy."""

    def assertCheck(self, student, reference, expected):
        self.assertEqual(check_answer(student, reference), expected,
                         f'{student!r} vs {reference!r}')

    def test_numbers_in_any_notation(self):
        self.assertCheck('0,5', '1/2', 'ok')
        self.assertCheck(r'\frac12', '0.5', 'ok')
        self.assertCheck(r'$\frac{1}{2}$', '$0{,}5$', 'ok')
        self.assertCheck('3', '3.0', 'ok')
        self.assertCheck('0.75', r'-\frac34', 'wrong')

    def test_sets_and_roots(self):
        self.assertCheck('2; 3', '3; 2', 'ok')
        self.assertCheck('{1;2}', r'\{2;1\}', 'ok')
        self.assertCheck('x=2; x=3', '2; 3', 'ok')
        self.assertCheck(r'\pm 2', '2; -2', 'ok')
        self.assertCheck('2', r'\pm 2', 'wrong')
        self.assertCheck('x=2', '2', 'ok')

    def test_intervals(self):
        self.assertCheck('(1;3]', '(1; 3]', 'ok')
        self.assertCheck('(1;3)', '(1;3]', 'wrong')
        self.assertCheck(r'(-\infty; 3]', '(−∞;3]', 'ok')
        self.assertCheck(r'(-3;3)', r'$\left(-3;\ 3\right)$', 'ok')
        self.assertCheck(r'(-\infty;-3)\cup(3;+\infty)',
                         r'(3;+\infty)\cup(-\infty;-3)', 'ok')
        # Два поля «от/до» без скобок: сравниваются только концы
        self.assertEqual(check_interval_fields('-3', '3', '(-3;3]'), 'ok')
        self.assertEqual(check_interval_fields('', '3', r'(-\infty;3]'), 'ok')
        self.assertEqual(check_interval_fields('1', '4', '(1;3]'), 'wrong')
        self.assertEqual(check_interval_fields('', '', '(1;3]'), '')

    def test_expressions_via_sympy(self):
        self.assertCheck('x^2-1', '(x-1)(x+1)', 'ok')
        self.assertCheck(r'\frac{x}{2}', '0.5x', 'ok')
        self.assertCheck(r'2\sqrt{2}', r'\sqrt{8}', 'ok')
        self.assertCheck('y=2x+1', 'y = 1 + 2x', 'ok')
        self.assertCheck('x+1', 'x+2', 'wrong')
        self.assertCheck(r'\sqrt{2}', '1,41', 'wrong')

    def test_words_and_unparsable(self):
        self.assertCheck('нет решений', 'Нет решений', 'ok')
        self.assertCheck('нет решений', '2', 'wrong')
        # Что не разобралось — не «неверно», а «не разобрано»
        self.assertCheck(r'\taskpic{x}', '5', 'unknown')
        self.assertCheck('корней нет при a<0', 'нет корней', 'unknown')
        self.assertCheck('', '5', '')
        self.assertCheck('5', '', '')
        self.assertCheck('x' * 400, 'x', 'unknown')

    def test_no_eval_of_student_input(self):
        # parse_expr/sympify исполняли бы это через eval — здесь только грамматика
        self.assertCheck("__import__('os').system('true')", '5', 'unknown')


class AutoCheckFlowTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.assignment = make_assignment(self.teacher, self.student)
        self.task = self.assignment.worksheet.ordered_items()[0].task
        # Эталон задачи из make_worksheet — «0; 2»
        self.url = reverse('save_answers', args=[self.assignment.pk])
        self.detail = reverse('assignment_detail', args=[self.assignment.pk])
        self.client.login(username='student1', password='pass12345')

    def _save(self, value, xhr=True):
        extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if xhr else {}
        return self.client.post(
            self.url, {f'task{self.task.pk}_text': value}, **extra)

    def test_check_stored_and_attempts_counted(self):
        self._save('x=2; x=0')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.assertIsNotNone(submission.checked_at)
        self.assertEqual(submission.check_attempts, 1)
        self._save('x=2; x=0')  # то же значение — не попытка
        self._save('1; 2')
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'wrong')
        self.assertEqual(submission.check_attempts, 2)

    def test_teacher_only_mode_hides_result_from_student(self):
        response = self._save('0; 2')
        self.assertNotIn('checks', response.json())
        response = self.client.get(self.detail)
        self.assertFalse(response.context['show_checks'])
        self.assertNotContains(response, 'совпало')
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(self.detail)
        self.assertNotContains(response, 'совпало')

    def test_after_submit_mode(self):
        self.assignment.check_visibility = Assignment.CHECK_AFTER_SUBMIT
        self.assignment.save()
        response = self._save('0; 2')
        self.assertNotIn('checks', response.json())
        self.assertNotContains(self.client.get(self.detail), '✓ совпало')
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(self.detail)
        self.assertContains(response, '✓ совпало')
        # Эталон ученику не показывается ни в одном режиме
        self.assertNotContains(response, 'Эталон')

    def test_live_mode_returns_checks_in_json(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        response = self._save('7')
        self.assertEqual(response.json()['checks'],
                         {f'task{self.task.pk}': 'wrong'})
        response = self.client.get(self.detail)
        self.assertContains(response, '✗ не совпало')
        self.assertContains(response, f'data-check="task{self.task.pk}"')

    def test_pages_survive_rubric_and_text_items(self):
        # Рубрики и текстовые вставки — строки без задачи и ответа;
        # пересчёт сверки не должен на них падать ни у ученика, ни у учителя
        WorksheetItem.objects.create(
            worksheet=self.assignment.worksheet, rubric='Разминка', order=5)
        WorksheetItem.objects.create(
            worksheet=self.assignment.worksheet, text_latex='Подсказка',
            order=15)
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        self._save('0; 2')
        self.assertEqual(self.client.get(self.detail).status_code, 200)
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Разминка')

    def test_review_shows_badge_and_recomputes_after_reference_change(self):
        self._save('0; 2')
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        self.client.login(username='teacher1', password='pass12345')
        review_url = reverse('review_assignment', args=[self.assignment.pk])
        self.assertContains(self.client.get(review_url), '✓ совпало')
        # Учитель исправил эталон — сверка пересчитывается при открытии проверки
        self.task.answer_latex = '1; 3'
        self.task.save()
        response = self.client.get(review_url)
        self.assertContains(response, '✗ не совпало')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'wrong')

    def test_teacher_sets_visibility_on_assign_and_review(self):
        self.client.login(username='teacher1', password='pass12345')
        worksheet = make_worksheet(self.teacher, title='Другой')
        self.client.post(
            reverse('assign_worksheet', args=[worksheet.pk]),
            {'students': [self.student.pk], 'grade_scale': 'words',
             'check_visibility': 'live'})
        created = Assignment.objects.get(worksheet=worksheet)
        self.assertEqual(created.check_visibility, Assignment.CHECK_LIVE)
        # Мусорное значение → режим по умолчанию
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]),
            {'action': 'save', 'check_visibility': 'everyone'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.check_visibility,
                         Assignment.CHECK_TEACHER)
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]),
            {'action': 'save', 'check_visibility': 'after_submit'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.check_visibility,
                         Assignment.CHECK_AFTER_SUBMIT)

    def test_interval_and_number_types_checked(self):
        self.task.answer_type = Task.ANSWER_INTERVAL
        self.task.answer_latex = r'(-\infty; 3]'
        self.task.save()
        self.client.post(self.url, {f'task{self.task.pk}_low': '',
                                    f'task{self.task.pk}_high': '3'})
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.task.answer_type = Task.ANSWER_NUMBER
        self.task.answer_latex = r'\frac{1}{4}'
        self.task.save()
        self.client.post(self.url, {f'task{self.task.pk}_number': '0,25'})
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'ok')
