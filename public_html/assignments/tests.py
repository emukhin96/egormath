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
            {'students': [self.student.pk]})
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
            {'students': [foreign_student.pk]})
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
        # Без маски свободного поля у ученика нет; старый ответ виден как есть
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, f'name="task{task.pk}_text"')
        self.assertContains(response, 'answer-readonly')
        self.assertContains(response, 'Краткий ответ для этой задачи не предусмотрен')
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

    def test_mask_renders_controls_and_legacy_readonly(self):
        """С маской ученик видит контролы по слотам (simplify — math-field),
        без маски — только подсказку про фото; старый свободный ответ после
        сдачи показывается как есть."""
        task = self.tasks[0]
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, f'name="task{task.pk}_text"')
        notes = len(self.tasks)
        self.assertContains(response, 'mask-photo-note', count=notes)
        task.answer_mask = r'Упростите: {{simplify: \frac{2}{a+3}}}'
        task.save()
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'mask-answer')
        self.assertContains(response, '<math-field')
        self.assertContains(response, f'name="task{task.pk}_s1"')
        self.assertContains(response, 'mathlive')
        self.assertContains(response, 'mask-photo-note', count=notes - 1)
        # Старый ответ без маски после сдачи — только для чтения
        task.answer_mask = ''
        task.save()
        Submission.objects.create(
            assignment=self.assignment, task=task, answer_text=r'нет решений при $a<0$')
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, 'mathlive')
        self.assertContains(response, 'answer-readonly')
        self.assertContains(response, 'нет решений при $a&lt;0$')

    def test_mask_answers_saved_to_json(self):
        """Значения слотов сохраняются в answer_json, display_answer — маска с подстановкой."""
        task = self.tasks[0]
        task.answer_mask = 'Меньшая сторона {{number: 10}} см, площадь {{number: 300}} см$^2$'
        task.save()
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': '10', f'task{task.pk}_s2': '30'})
        submission = Submission.objects.get(task=task)
        self.assertEqual(submission.answer_json, {'s1': '10', 's2': '30'})
        self.assertIn('10', submission.display_answer)
        self.assertIn('30', submission.display_answer)
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'value="30"')

    def test_save_subitem_answers(self):
        """У задачи с подпунктами ответы сохраняются отдельно (SubmissionPart)."""
        item = self.assignment.worksheet.ordered_items()[0]
        task = item.task
        task.answer_type = Task.ANSWER_NUMBER
        task.save()
        s1 = TaskSubitem.objects.create(
            task=task, order=10, text_latex='$1+1$', answer_mask='{{number: 2}}')
        s2 = TaskSubitem.objects.create(
            task=task, order=20, text_latex='$2+2$', answer_mask='{{number: 4}}')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]), {
                f'task{task.pk}_sub{s1.pk}_s1': '2',
                f'task{task.pk}_sub{s2.pk}_s1': '4',
            })
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        parts = {p.subitem_id: p for p in submission.parts.all()}
        self.assertEqual(parts[s1.pk].answer_json, {'s1': '2'})
        self.assertEqual(parts[s2.pk].answer_json, {'s1': '4'})
        # Страница задания показывает ответы по подпунктам
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, f'task{task.pk}_sub{s1.pk}_s1')
        self.assertContains(response, 'value="4"')

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
                f'sub{submission.pk}_done': 'on',
                f'sub{submission.pk}_comment': 'Верно, но оформи решение.',
                'action': 'complete',
            })
        self.assertRedirects(response, reverse('dashboard'))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_REVIEWED)
        review = Review.objects.get(submission=submission)
        self.assertTrue(review.done)
        # Итог — доля выполненных задач, без шкал
        self.assertEqual(self.assignment.result(),
                         {'done': 1, 'total': 2, 'percent': 50})

        # Ученик видит комментарий и итог
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'Верно, но оформи решение.')
        self.assertContains(response, 'выполнено')
        self.assertContains(response, '1 из 2')
        self.assertContains(response, '(50%)')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '1/2 (50%)')

    def test_review_form_has_no_grade_scale(self):
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, 'Выполнено')
        self.assertNotContains(response, 'Отметка')
        self.assertNotContains(response, 'Баллы')
        self.assertNotContains(response, 'name="check_visibility"')
        # Режим сверки показан текстом и объявлен неизменяемым
        self.assertContains(response, 'не меняется')

    def test_done_checkbox_defaults_to_auto_check(self):
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        # Эталон задачи — «0; 2»: ответ ученика «x = 2» не совпадает
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertFalse(response.context['rows'][0]['auto_ok'])
        submission.answer_text = '2; 0'
        submission.run_check(self.task.effective_answer_latex)
        submission.save()
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertTrue(response.context['rows'][0]['auto_ok'])
        self.assertRegex(
            response.content.decode(),
            rf'name="sub{submission.pk}_done" data-review-done\s+checked')

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

    def test_unchecked_without_comment_keeps_explicit_not_done(self):
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        Review.objects.create(
            submission=submission, done=True, reviewer=self.teacher)
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{submission.pk}_comment': '',
                'action': 'save',
            })
        review = Review.objects.get(submission=submission)
        self.assertFalse(review.done)
        # Повторное открытие не включает флажок через auto_ok
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertNotRegex(
            response.content.decode(),
            rf'name="sub{submission.pk}_done"[^>]*checked')

    def test_result_ignores_hidden_done_and_counts_duplicate_items(self):
        items = list(self.assignment.worksheet.items.order_by('order'))
        first, second = items[0], items[1]
        first_sub = Submission.objects.get(
            assignment=self.assignment, task=first.task)
        Review.objects.create(
            submission=first_sub, done=True, reviewer=self.teacher)
        self.assertEqual(self.assignment.result(),
                         {'done': 1, 'total': 2, 'percent': 50})
        self.assignment.hidden_items.add(first)
        self.assertEqual(self.assignment.result(),
                         {'done': 0, 'total': 1, 'percent': 0})
        self.assignment.hidden_items.clear()
        WorksheetItem.objects.create(
            worksheet=self.assignment.worksheet, task=first.task, order=90)
        self.assertEqual(self.assignment.result(),
                         {'done': 2, 'total': 3, 'percent': 67})

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
            submission=hidden_sub, done=True, reviewer=self.teacher)
        self.assignment.hidden_items.add(hidden_item)
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{visible_sub.pk}_comment': 'Не дорешано',
                'action': 'save',
            })
        self.assertTrue(Review.objects.filter(
            submission=hidden_sub, done=True).exists())
        visible_review = Review.objects.get(submission=visible_sub)
        self.assertFalse(visible_review.done)
        self.assertEqual(visible_review.comment, 'Не дорешано')

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
                f'sub{submission.pk}_done': 'on',
                f'sub{submission.pk}_comment': '',
                'action': 'save',
            })
        self.assertTrue(Review.objects.get(submission=submission).done)

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
        # Эталон задачи из make_worksheet — «0; 2»; ученик отвечает по маске
        self.task.answer_mask = 'Корни: {{set: 0; 2}}'
        self.task.save()
        self.field = f'task{self.task.pk}_s1'
        self.url = reverse('save_answers', args=[self.assignment.pk])
        self.detail = reverse('assignment_detail', args=[self.assignment.pk])
        self.client.login(username='student1', password='pass12345')

    def _save(self, value, xhr=True):
        extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if xhr else {}
        return self.client.post(self.url, {self.field: value}, **extra)

    def _check(self, value=None, xhr=True):
        """Кнопка «Проверить»: шлёт всю форму, как и автосохранение."""
        extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if xhr else {}
        data = {} if value is None else {self.field: value}
        return self.client.post(
            reverse('check_task', args=[self.assignment.pk, self.task.pk]),
            data, **extra)

    def test_check_stored_on_save_but_attempts_count_button_presses(self):
        self._save('x=2; x=0')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.assertEqual(submission.check_json, {'s1': 'ok'})
        self.assertIsNotNone(submission.checked_at)
        self.assertFalse(submission.check_revealed)
        self.assertEqual(submission.check_attempts, 0)
        self._save('1; 2')
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'wrong')
        self.assertEqual(submission.check_attempts, 0)

    def test_teacher_only_mode_hides_result_from_student(self):
        response = self._save('0; 2')
        self.assertNotIn('checks', response.json())
        response = self.client.get(self.detail)
        self.assertFalse(response.context['show_checks'])
        self.assertNotContains(response, 'верно')
        self.assertNotContains(response, 'Проверить<')
        # Кнопки нет — и её URL закрыт
        self.assertEqual(self._check().status_code, 403)
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(self.detail)
        self.assertNotContains(response, 'верно')

    def test_after_submit_mode(self):
        self.assignment.check_visibility = Assignment.CHECK_AFTER_SUBMIT
        self.assignment.save()
        response = self._save('0; 2')
        self.assertNotIn('checks', response.json())
        response = self.client.get(self.detail)
        self.assertNotContains(response, '✓ верно')
        self.assertNotContains(response, 'data-check-task')
        self.assertEqual(self._check().status_code, 403)
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(self.detail)
        self.assertContains(response, '✓ верно')
        # Эталон ученику не показывается ни в одном режиме
        self.assertNotContains(response, 'Эталон')
        # Возврат на доработку не прячет уже показанную сверку
        self.assignment.status = Assignment.STATUS_RETURNED
        self.assignment.save()
        response = self.client.get(self.detail)
        self.assertTrue(self.assignment.is_editable_by_student)
        self.assertContains(response, '✓ верно')

    def test_live_mode_reveals_only_by_button(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        # Автосохранение результат не выдаёт — иначе ответ подбирался бы по бейджу
        response = self._save('7')
        self.assertNotIn('checks', response.json())
        response = self.client.get(self.detail)
        # Бейджи — по слотам маски
        self.assertContains(response, f'data-check="task{self.task.pk}_s1"')
        self.assertContains(response, 'data-check-task')
        self.assertNotContains(response, '✗ неверно')
        # Кнопка «Проверить» сохраняет присланное и раскрывает результат
        response = self._check('7')
        self.assertEqual(response.json()['checks'], {
            f'task{self.task.pk}': 'wrong',
            f'task{self.task.pk}_s1': 'wrong',
        })
        self.assertContains(self.client.get(self.detail), '✗ неверно')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.check_attempts, 1)
        # Новый ответ — бейдж прячется до следующего нажатия
        self._save('0; 2')
        self.assertNotContains(self.client.get(self.detail), 'верно</span>')
        self._check()
        self.assertContains(self.client.get(self.detail), '✓ верно')
        submission.refresh_from_db()
        self.assertEqual(submission.check_attempts, 2)
        # Без JS — redirect обратно к задаче
        response = self._check(xhr=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith('#task-1'))

    def test_check_button_without_answer(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        response = self._check()
        self.assertEqual(response.json()['checks'], {})
        self.assertIn('введите ответ', response.json()['message'])
        self.assertEqual(Submission.objects.get(
            assignment=self.assignment, task=self.task).check_attempts, 0)

    def test_check_button_disabled_without_mask(self):
        # Без маски сверять нечего: кнопка неактивна, поля ввода нет,
        # прямой запрос ничего не раскрывает и попыткой не считается
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        self.task.answer_mask = ''
        self.task.save()
        response = self.client.get(self.detail)
        self.assertFalse(response.context['rows'][0]['short_answer'])
        self.assertNotContains(response, f'name="{self.field}"')
        self.assertRegex(
            response.content.decode(),
            rf'data-check-task="task{self.task.pk}"[^>]*\sdisabled\s')
        response = self._check('7')
        self.assertEqual(response.status_code, 400)
        self.assertIn('нет маски', response.json()['message'])
        self.assertFalse(Submission.objects.filter(
            assignment=self.assignment, task=self.task,
            check_revealed=True).exists())
        # Режим «только развёрнутый ответ» — только фото даже при маске
        self.task.answer_mask = '{{number: 5}}'
        self.task.answer_mode = Task.MODE_EXTENDED
        self.task.save()
        response = self.client.get(self.detail)
        self.assertFalse(response.context['rows'][0]['short_answer'])
        self.assertNotContains(response, 'mask-answer')
        self.assertContains(response, 'mask-photo-note')
        # У задачи с подпунктами хватает маски хотя бы на одном подпункте
        self.task.answer_mode = Task.MODE_SHORT
        self.task.answer_mask = ''
        self.task.save()
        TaskSubitem.objects.create(task=self.task, order=1, text_latex='а')
        TaskSubitem.objects.create(
            task=self.task, order=2, text_latex='б', answer_mask='{{number: 5}}')
        response = self.client.get(self.detail)
        self.assertTrue(response.context['rows'][0]['short_answer'])

    def test_check_button_with_subitems(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        a = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='а', answer_mask='{{number: 1}}')
        b = TaskSubitem.objects.create(
            task=self.task, order=2, text_latex='б', answer_mask='{{number: 2}}')
        response = self.client.post(
            reverse('check_task', args=[self.assignment.pk, self.task.pk]),
            {f'task{self.task.pk}_sub{a.pk}_s1': '1',
             f'task{self.task.pk}_sub{b.pk}_s1': '3'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['checks'], {
            f'task{self.task.pk}_sub{a.pk}': 'ok',
            f'task{self.task.pk}_sub{a.pk}_s1': 'ok',
            f'task{self.task.pk}_sub{b.pk}': 'wrong',
            f'task{self.task.pk}_sub{b.pk}_s1': 'wrong',
        })
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.check_attempts, 1)
        self.assertTrue(all(p.check_revealed for p in submission.parts.all()))

    def test_auto_ok_requires_every_subitem(self):
        a = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='а', answer_latex='1')
        b = TaskSubitem.objects.create(
            task=self.task, order=2, text_latex='б', answer_latex='2')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{self.task.pk}_sub{a.pk}_text': '1'})
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertFalse(response.context['rows'][0]['auto_ok'])
        self.client.login(username='student1', password='pass12345')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{self.task.pk}_sub{a.pk}_text': '1',
             f'task{self.task.pk}_sub{b.pk}_text': '2'})
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertTrue(response.context['rows'][0]['auto_ok'])

    def test_photo_button_per_task_and_teacher_toggle(self):
        response = self.client.get(self.detail)
        self.assertContains(response, f'photo-form-{self.task.pk}')
        self.assertContains(response, 'Фото решения')
        self.assignment.allow_photos = False
        self.assignment.save()
        response = self.client.get(self.detail)
        self.assertNotContains(response, 'Фото решения')
        response = self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, self.task.pk]),
            {'photos': fake_photo()})
        self.assertEqual(response.status_code, 403)

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
        self.assertContains(self.client.get(review_url), '✓ верно')
        # Учитель исправил маску — сверка пересчитывается при открытии проверки
        self.task.answer_mask = 'Корни: {{set: 1; 3}}'
        self.task.save()
        response = self.client.get(review_url)
        self.assertContains(response, '✗ неверно')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'wrong')

    def test_review_shows_filled_mask_with_slot_badges_and_reference(self):
        """Учителю — заполненная маска, бейдж у каждого слота и эталон маски;
        формула из math-field показывается как $…$, а не кодом."""
        self.task.answer_mask = r'Корни: {{set: 0; 2}}, разложение {{factor: x(x-2)}}'
        self.task.save()
        self.client.post(self.url, {self.field: '0; 2',
                                    f'task{self.task.pk}_s2': '(x-2)x'})
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, 'mask-answer')
        self.assertContains(response, f'data-check="task{self.task.pk}_s1"')
        self.assertContains(response, f'data-check="task{self.task.pk}_s2"')
        self.assertContains(response, '✓ верно', count=2)
        self.assertContains(response, 'Маска с эталонами')
        self.assertContains(response, '[0; 2]')
        self.assertContains(response, '$x(x-2)$')
        self.assertContains(response, '$(x-2)x$')

    def test_visibility_set_on_assign_and_locked_afterwards(self):
        self.client.login(username='teacher1', password='pass12345')
        worksheet = make_worksheet(self.teacher, title='Другой')
        student2 = make_student(self.teacher, 'student2')
        assign_url = reverse('assign_worksheet', args=[worksheet.pk])
        detail_url = reverse('worksheet_detail', args=[worksheet.pk])
        # До выдачи режим выбирается свободно
        response = self.client.get(detail_url)
        self.assertIsNone(response.context['locked_check'])
        self.assertNotContains(response, 'Уже задано ученикам')
        self.client.post(assign_url, {'students': [self.student.pk],
                                      'check_visibility': 'live',
                                      'allow_photos': 'on'})
        created = Assignment.objects.get(worksheet=worksheet)
        self.assertEqual(created.check_visibility, Assignment.CHECK_LIVE)
        self.assertTrue(created.allow_photos)
        # Листок выдан: селект заблокирован, а присланное значение игнорируется
        response = self.client.get(detail_url)
        self.assertEqual(response.context['locked_check'], Assignment.CHECK_LIVE)
        self.assertContains(response, 'Уже задано ученикам')
        self.assertContains(response, 'id="a_check" style="max-width:340px" disabled')
        self.client.post(assign_url, {'students': [student2.pk],
                                      'check_visibility': 'teacher'})
        second = Assignment.objects.get(worksheet=worksheet, student=student2)
        self.assertEqual(second.check_visibility, Assignment.CHECK_LIVE)
        # Фото — отдельная настройка каждой выдачи, чекбокс не прислан → выключено
        self.assertFalse(second.allow_photos)
        # На экране проверки режим сменить нельзя
        self.client.post(
            reverse('save_review', args=[self.assignment.pk]),
            {'action': 'save', 'check_visibility': 'after_submit'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.check_visibility,
                         Assignment.CHECK_TEACHER)

    def test_range_and_number_slots_checked(self):
        self.task.answer_mask = r'{{range: (-\infty; 3]}}'
        self.task.save()
        self._save(r'x \le 3')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.task.answer_mask = r'{{number: \frac{1}{4}}}'
        self.task.save()
        self._save('0,25')
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'ok')

    def test_legacy_answer_checked_until_mask_filled(self):
        """Ответ, сданный до появления маски, сверяется по старым полям и
        показывается учителю; заполненные слоты имеют приоритет."""
        self.task.answer_mask = ''
        self.task.answer_type = Task.ANSWER_NUMBER
        self.task.answer_latex = r'\frac{1}{4}'
        self.task.save()
        self.client.post(self.url, {f'task{self.task.pk}_number': '0,25'})
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.assertEqual(submission.display_answer, '0,25')
        self.task.answer_mask = '{{number: 5}}'
        self.task.save()
        self.client.get(self.detail)
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'ok')
        self._save('5')
        submission.refresh_from_db()
        self.assertEqual(submission.display_answer, '[5]')
        self.assertEqual(submission.check_json, {'s1': 'ok'})

    def test_legacy_answer_still_shown_after_mask_added(self):
        """Пока слоты пусты, ученик видит старый свободный ответ — и форму маски."""
        self.task.answer_mask = ''
        self.task.answer_type = Task.ANSWER_NUMBER
        self.task.answer_latex = r'\frac{1}{4}'
        self.task.save()
        self.client.post(self.url, {f'task{self.task.pk}_number': '0,25'})
        self.task.answer_mask = '{{number: 5}}'
        self.task.save()
        response = self.client.get(self.detail)
        self.assertContains(response, '0,25')
        self.assertContains(response, f'name="task{self.task.pk}_s1"')

    def test_cleared_order_slot_is_saved(self):
        self.task.answer_mask = '{{order: a|b}}'
        self.task.save()
        self.client.post(self.url, {
            f'task{self.task.pk}_s1_0': '0',
            f'task{self.task.pk}_s1_1': '1',
        })
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.answer_json, {'s1': '0|1'})
        self.client.post(self.url, {
            f'task{self.task.pk}_s1_0': '',
            f'task{self.task.pk}_s1_1': '',
        })
        submission.refresh_from_db()
        self.assertEqual(submission.answer_json.get('s1'), '')
