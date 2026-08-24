import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from problems.models import Task, TaskSubitem
from problems.tests import make_student, make_teacher
from worksheets.tests import make_worksheet

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

    def test_foreign_teacher_cannot_review(self):
        make_teacher('teacher2')
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 404)
