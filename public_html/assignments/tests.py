import io
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from problems.models import Task, TaskSubitem
from problems.tests import make_student, make_teacher
from accounts.models import Profile, StudentGroup
from worksheets.models import Worksheet, WorksheetItem
from worksheets.tests import make_worksheet

from .check_answer import check_answer, check_interval_fields
from .models import (Assignment, Review, Submission, SubmissionCheckAttempt,
                     SubmissionPart, SubmissionPhoto)


def make_assignment(teacher, student, **kwargs):
    worksheet = make_worksheet(teacher)
    return Assignment.objects.create(
        worksheet=worksheet, student=student, assigned_by=teacher, **kwargs)


def order_form(task, *chosen, prefix=None):
    """POST слота order: исходные индексы → непрозрачные токены формы."""
    from .checks import parse_mask
    prefix = prefix or f'task{task.pk}'
    slot = parse_mask(task.answer_mask).slots[0]
    tokens = slot.order_tokens(prefix)
    data = {}
    for k, idx in enumerate(chosen):
        data[f'{prefix}_{slot.name}_{k}'] = (
            tokens[idx] if idx is not None and idx != '' else '')
    return data


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

    def test_teacher_changes_one_assignment_status_from_worksheet(self):
        assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

        page = self.client.get(reverse(
            'worksheet_detail', args=[self.worksheet.pk]))
        self.assertContains(
            page, reverse('review_assignment', args=[assignment.pk]))
        self.assertContains(page, f'assignment-status-{assignment.pk}')

        response = self.client.post(reverse(
            'assignment_status_update', args=[assignment.pk]), {
                'status': Assignment.STATUS_SUBMITTED,
            })

        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, Assignment.STATUS_SUBMITTED)
        self.assertIsNotNone(assignment.submitted_at)

    def test_teacher_cannot_change_foreign_assignment_status(self):
        other_teacher = make_teacher('teacher2')
        foreign_student = make_student(other_teacher, 'student2')
        foreign = make_assignment(other_teacher, foreign_student)
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.post(reverse(
            'assignment_status_update', args=[foreign.pk]), {
                'status': Assignment.STATUS_REVIEWED,
            })

        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, Assignment.STATUS_ASSIGNED)


class SuperuserStudentVisibilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        self.student = User.objects.create_user(
            username='free-student', password='pass12345',
            first_name='Саша', last_name='Саморегистров')
        Profile.objects.create(user=self.student, role=Profile.ROLE_STUDENT)
        self.worksheet = make_worksheet(self.admin)

    def test_unattached_student_is_in_assignment_form(self):
        self.client.login(username='admin', password='pass12345')
        response = self.client.get(reverse('assignment_create'))
        self.assertContains(response, 'Саморегистров')
        self.assertIn(
            self.student, response.context['form'].fields['students'].queryset)

    def test_superuser_can_assign_unattached_student(self):
        self.client.login(username='admin', password='pass12345')
        response = self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk,
            'students': [self.student.pk],
            'check_visibility': Assignment.CHECK_TEACHER,
        })
        self.assertRedirects(response, reverse('assignment_list'))
        self.assertTrue(Assignment.objects.filter(
            worksheet=self.worksheet, student=self.student).exists())


class SuperuserAssignmentAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(
            self.teacher, title='Чужой листок')
        self.assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher, status=Assignment.STATUS_SUBMITTED,
            submitted_at=timezone.now())
        self.client.login(username='admin', password='pass12345')

    def test_global_list_and_owner_filter(self):
        own_student = make_student(self.admin, 'admin-student')
        own = make_assignment(
            self.admin, own_student, status=Assignment.STATUS_SUBMITTED,
            submitted_at=timezone.now())
        response = self.client.get(reverse('assignment_list'))
        self.assertEqual(response.context['stats']['total'], 2)
        self.assertContains(response, self.worksheet.title)
        self.assertContains(
            response, self.teacher.get_full_name() or self.teacher.username)

        response = self.client.get(
            reverse('assignment_list'), {'owner': self.teacher.pk})
        self.assertEqual(list(response.context['assignments']),
                         [self.assignment])

    def test_superuser_reviews_foreign_assignment_and_keeps_queue_filter(self):
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]),
            {'owner': self.teacher.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['queue_total'], 1)
        response = self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                'action': 'complete', 'owner': self.teacher.pk,
            })
        self.assertEqual(
            response.url,
            f"{reverse('assignment_list')}?owner={self.teacher.pk}")
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_REVIEWED)

    def test_superuser_assigns_foreign_worksheet_via_foreign_group(self):
        second = make_student(self.teacher, 'student2')
        group = StudentGroup.objects.create(
            teacher=self.teacher, name='Чужая группа')
        group.students.add(second)
        response = self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk,
            'groups': [group.pk],
            'check_visibility': Assignment.CHECK_TEACHER,
        })
        self.assertRedirects(response, reverse('assignment_list'))
        created = Assignment.objects.get(
            worksheet=self.worksheet, student=second)
        self.assertEqual(created.assigned_by, self.admin)
        self.assertEqual(created.worksheet.owner, self.teacher)

    def test_superuser_can_assign_from_worksheet_page(self):
        self.client.login(username='admin', password='pass12345')
        response = self.client.post(
            reverse('assign_worksheet', args=[self.worksheet.pk]),
            {'students': [self.student.pk]})
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.assertTrue(Assignment.objects.filter(
            worksheet=self.worksheet, student=self.student).exists())


class AssignmentWorkspaceTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.student2 = make_student(self.teacher, 'student2')
        self.worksheet = make_worksheet(self.teacher)
        self.group = StudentGroup.objects.create(
            teacher=self.teacher, name='8 класс')
        self.group.students.add(self.student)
        self.client.login(username='teacher1', password='pass12345')

    def test_list_is_teacher_scoped_and_filterable(self):
        submitted_at = timezone.now()
        submitted = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher, status=Assignment.STATUS_SUBMITTED,
            submitted_at=submitted_at)
        older_worksheet = make_worksheet(self.teacher, title='Сдано раньше')
        older_submitted = Assignment.objects.create(
            worksheet=older_worksheet, student=self.student,
            assigned_by=self.teacher, status=Assignment.STATUS_SUBMITTED,
            submitted_at=submitted_at - timedelta(days=1))
        Assignment.objects.create(
            worksheet=self.worksheet, student=self.student2,
            assigned_by=self.teacher, status=Assignment.STATUS_ASSIGNED,
            due_at=timezone.now() - timedelta(days=1))
        other_teacher = make_teacher('teacher2')
        foreign_student = make_student(other_teacher, 'student3')
        foreign_worksheet = make_worksheet(
            other_teacher, title='Чужой листок')
        foreign = Assignment.objects.create(
            worksheet=foreign_worksheet, student=foreign_student,
            assigned_by=other_teacher, status=Assignment.STATUS_SUBMITTED)

        response = self.client.get(reverse('assignment_list'))
        self.assertEqual(response.context['stats']['total'], 3)
        self.assertEqual(response.context['stats']['submitted'], 2)
        self.assertEqual(response.context['stats']['overdue'], 1)
        self.assertNotContains(response, foreign.worksheet.title)
        self.assertEqual(response.context['assignments'][0], older_submitted)

        response = self.client.get(
            reverse('assignment_list'), {'status': Assignment.STATUS_SUBMITTED})
        self.assertEqual(
            list(response.context['assignments']),
            [older_submitted, submitted])

    def test_catalog_groups_are_ordered_by_last_assignment_date(self):
        """Свежая выдача выше старой, даже если старая ждёт проверки."""
        old_worksheet = make_worksheet(self.teacher, title='Старая на проверке')
        old = Assignment.objects.create(
            worksheet=old_worksheet, student=self.student,
            assigned_by=self.teacher, status=Assignment.STATUS_SUBMITTED,
            submitted_at=timezone.now())
        Assignment.objects.filter(pk=old.pk).update(
            assigned_at=timezone.now() - timedelta(days=3))
        Assignment.objects.create(
            worksheet=self.worksheet, student=self.student2,
            assigned_by=self.teacher, status=Assignment.STATUS_ASSIGNED)

        response = self.client.get(reverse('assignment_list'))
        titles = [group['worksheet__title']
                  for group in response.context['worksheet_groups']]
        self.assertEqual(titles, [self.worksheet.title, 'Старая на проверке'])

    def test_catalog_dialog_updates_recipients_and_statuses(self):
        existing = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher)
        response = self.client.get(reverse('assignment_list'))
        self.assertContains(response, 'data-assignment-group-form')
        self.assertContains(response, 'Изменить')

        response = self.client.post(reverse(
            'assignment_group_update', args=[self.worksheet.pk]), {
                'students': [self.student2.pk],
                f'status_{self.student2.pk}': Assignment.STATUS_SUBMITTED,
            })
        self.assertRedirects(response, reverse('assignment_list'))
        self.assertFalse(Assignment.objects.filter(pk=existing.pk).exists())
        replacement = Assignment.objects.get(
            worksheet=self.worksheet, student=self.student2)
        self.assertEqual(replacement.status, Assignment.STATUS_SUBMITTED)
        self.assertIsNotNone(replacement.submitted_at)

    def test_catalog_review_requires_submitted_assignment(self):
        assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher)
        url = reverse('assignment_group_update', args=[self.worksheet.pk])
        data = {
            'students': [self.student.pk],
            f'status_{self.student.pk}': Assignment.STATUS_REVIEWED,
        }

        self.client.post(url, data)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, Assignment.STATUS_ASSIGNED)
        self.assertIsNone(assignment.reviewed_at)

        assignment.status = Assignment.STATUS_SUBMITTED
        assignment.submitted_at = timezone.now()
        assignment.save(update_fields=['status', 'submitted_at'])
        self.client.post(url, data)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, Assignment.STATUS_REVIEWED)
        self.assertIsNotNone(assignment.reviewed_at)

    def test_catalog_update_preserves_filters(self):
        Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher)
        url = (reverse('assignment_group_update', args=[self.worksheet.pk])
               + '?status=assigned&q=sheet')

        response = self.client.post(url, {
            'students': [self.student.pk],
            f'status_{self.student.pk}': Assignment.STATUS_ASSIGNED,
        })

        self.assertRedirects(
            response,
            reverse('assignment_list') + '?status=assigned&q=sheet')

    def test_foreign_teacher_cannot_update_assignment_group(self):
        other_teacher = make_teacher('teacher2')
        foreign_student = make_student(other_teacher, 'student3')
        foreign_worksheet = make_worksheet(
            other_teacher, title='Чужой листок')
        foreign = Assignment.objects.create(
            worksheet=foreign_worksheet, student=foreign_student,
            assigned_by=other_teacher)

        response = self.client.post(reverse(
            'assignment_group_update', args=[foreign_worksheet.pk]), {
                'students': [self.student.pk],
                f'status_{self.student.pk}': Assignment.STATUS_SUBMITTED,
            })

        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, Assignment.STATUS_ASSIGNED)
        self.assertTrue(Assignment.objects.filter(pk=foreign.pk).exists())

    def test_create_for_group_and_student_without_duplicates(self):
        response = self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk,
            'groups': [self.group.pk],
            'students': [self.student.pk, self.student2.pk],
            'due_at': '2030-09-14T18:30',
            'check_visibility': Assignment.CHECK_LIVE,
            'allow_photos': 'on',
        })
        self.assertRedirects(response, reverse('assignment_list'))
        assignments = Assignment.objects.filter(worksheet=self.worksheet)
        self.assertEqual(assignments.count(), 2)
        self.assertEqual(
            set(assignments.values_list('student_id', flat=True)),
            {self.student.pk, self.student2.pk})
        self.assertTrue(all(a.allow_photos for a in assignments))
        self.assertTrue(all(
            a.check_visibility == Assignment.CHECK_LIVE for a in assignments))

        # Повторная выдача не создаёт вторую запись и не меняет условия.
        self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk,
            'students': [self.student.pk],
            'check_visibility': Assignment.CHECK_TEACHER,
        })
        self.assertEqual(assignments.count(), 2)
        self.assertEqual(
            assignments.get(student=self.student).check_visibility,
            Assignment.CHECK_LIVE)

    def test_new_group_member_inherits_tasks_hidden_for_whole_group(self):
        """Задача, скрытая «для группы целиком», скрыта и у добавленного позже."""
        item = self.worksheet.items.filter(task__isnull=False).first()
        self.group.students.set([self.student])
        self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk, 'groups': [self.group.pk],
            'check_visibility': Assignment.CHECK_LIVE})
        first = Assignment.objects.get(worksheet=self.worksheet, student=self.student)
        first.hidden_items.add(item)
        # В группу добавили ученика и снова выдали листок группе
        self.group.students.add(self.student2)
        self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk, 'groups': [self.group.pk],
            'check_visibility': Assignment.CHECK_LIVE})
        second = Assignment.objects.get(worksheet=self.worksheet, student=self.student2)
        self.assertEqual(list(second.source_groups.all()), [self.group])
        self.assertEqual(list(second.hidden_items.all()), [item])
        # Индивидуальная выдача группу не наследует и задачи не скрывает
        third = make_student(self.teacher, 'student3')
        self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk, 'students': [third.pk],
            'check_visibility': Assignment.CHECK_LIVE})
        self.assertFalse(Assignment.objects.get(student=third).hidden_items.exists())

    def test_locked_check_mode_is_visible_and_used_for_new_student(self):
        Assignment.objects.create(
            worksheet=self.worksheet, student=self.student,
            assigned_by=self.teacher,
            check_visibility=Assignment.CHECK_LIVE)
        response = self.client.get(
            reverse('assignment_create'), {'worksheet': self.worksheet.pk})
        form = response.context['form']
        self.assertTrue(form.fields['check_visibility'].disabled)
        self.assertEqual(
            form.fields['check_visibility'].initial, Assignment.CHECK_LIVE)
        self.assertContains(response, 'Редактировать назначения')
        self.assertContains(response, '— уже назначено')
        self.assertRegex(
            response.content.decode(),
            rf'name="students" value="{self.student.pk}"[^>]*disabled')

        # Даже подменённый POST не меняет общий режим для нового ученика.
        response = self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk,
            'students': [self.student2.pk],
            'check_visibility': Assignment.CHECK_TEACHER,
        })
        self.assertRedirects(response, reverse('assignment_list'))
        created = Assignment.objects.get(
            worksheet=self.worksheet, student=self.student2)
        self.assertEqual(created.check_visibility, Assignment.CHECK_LIVE)

    def test_create_rejects_empty_recipients_and_foreign_objects(self):
        response = self.client.post(reverse('assignment_create'), {
            'worksheet': self.worksheet.pk,
            'check_visibility': Assignment.CHECK_TEACHER,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Выберите хотя бы одну группу')

        other_teacher = make_teacher('teacher2')
        foreign_student = make_student(other_teacher, 'student3')
        foreign_worksheet = make_worksheet(other_teacher, title='Чужой листок')
        response = self.client.post(reverse('assignment_create'), {
            'worksheet': foreign_worksheet.pk,
            'students': [foreign_student.pk],
            'check_visibility': Assignment.CHECK_TEACHER,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Assignment.objects.filter(
            worksheet=foreign_worksheet, assigned_by=self.teacher).exists())

    def test_student_cannot_open_teacher_workspace(self):
        self.client.login(username='student1', password='pass12345')
        self.assertEqual(
            self.client.get(reverse('assignment_list')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('assignment_create')).status_code, 403)

    def test_teacher_navigation_contains_assignments(self):
        response = self.client.get(reverse('assignment_list'))
        # Активность отмечена на группе меню: ссылка «Задания» + подразделы
        self.assertContains(response, 'href="/assignments/?kind=ordinary">Задания</a>')
        self.assertRegex(
            response.content.decode(),
            r'class="nav-group is-active">\s*<a href="/assignments/\?kind=ordinary"')

    @override_settings(TIME_ZONE='Europe/Moscow')
    def test_due_filters_use_local_date_and_expected_ranges(self):
        # В Москве уже 1 сентября, в UTC ещё 31 августа.
        now = datetime(2026, 8, 31, 21, 30, tzinfo=dt_timezone.utc)

        def assignment(title, due_at):
            worksheet = Worksheet.objects.create(
                owner=self.teacher, title=title)
            return Assignment.objects.create(
                worksheet=worksheet, student=self.student,
                assigned_by=self.teacher, due_at=due_at)

        today = assignment('Сегодня', now + timedelta(minutes=30))
        overdue = assignment('Вчера', now - timedelta(hours=2))
        week = assignment('На неделе', now + timedelta(days=3))
        assignment('Позже', now + timedelta(days=8))

        with mock.patch('django.utils.timezone.now', return_value=now):
            response = self.client.get(
                reverse('assignment_list'), {'due': 'today'})
            self.assertEqual(list(response.context['assignments']), [today])

            response = self.client.get(
                reverse('assignment_list'), {'due': 'overdue'})
            self.assertEqual(list(response.context['assignments']), [overdue])

            response = self.client.get(
                reverse('assignment_list'), {'due': 'week'})
            self.assertEqual(
                set(response.context['assignments']), {today, week})

    def test_search_and_pagination(self):
        target = Assignment.objects.create(
            worksheet=Worksheet.objects.create(
                owner=self.teacher, title='Алгебра: параметры'),
            student=self.student, assigned_by=self.teacher)
        Assignment.objects.create(
            worksheet=Worksheet.objects.create(
                owner=self.teacher, title='Геометрия'),
            student=self.student2, assigned_by=self.teacher)
        response = self.client.get(
            reverse('assignment_list'), {'q': 'параметры'})
        self.assertEqual(list(response.context['assignments']), [target])

        for index in range(31):
            Assignment.objects.create(
                worksheet=Worksheet.objects.create(
                    owner=self.teacher, title=f'Листок {index:02}'),
                student=self.student, assigned_by=self.teacher)
        response = self.client.get(reverse('assignment_list'))
        self.assertEqual(response.context['page'].paginator.count, 33)
        self.assertEqual(len(response.context['assignments']), 30)
        response = self.client.get(reverse('assignment_list'), {'page': 2})
        self.assertEqual(len(response.context['assignments']), 3)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='egormath-test-media-'))
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
        task.answer_mask = '{{equation: x=2}}'
        task.save()
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': 'x = 2'})
        self.assertRedirects(
            response, reverse('assignment_detail', args=[self.assignment.pk]))
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        self.assertEqual(submission.answer_json['s1'], 'x = 2')

    def test_autosave_reuses_check_of_unchanged_formula_slot(self):
        from assignments.checks import formulas
        task = self.tasks[0]
        task.answer_mask = '{{expression: a+27}}'
        task.save()
        formulas._checked.cache_clear()
        url = reverse('save_answers', args=[self.assignment.pk])
        self.client.post(url, {f'task{task.pk}_s1': '27+a'})
        submission = Submission.objects.get(assignment=self.assignment, task=task)
        self.assertEqual(submission.auto_check, 'ok')
        # Форма приходит целиком при каждом автосохранении: слот с прежним
        # значением не запускает дочерний процесс под блокировкой задания.
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker') as worker:
            self.client.post(url, {f'task{task.pk}_s1': '27+a'})
            worker.assert_not_called()
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'ok')
        self.assertEqual(submission.check_json, {'s1': 'ok'})

        response = self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        # Ответы созданы для всех задач
        self.assertEqual(self.assignment.submissions.count(), len(self.tasks))

        # После отправки редактирование запрещено
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': 'меняю ответ'})
        self.assertEqual(response.status_code, 403)

    def test_submit_without_draft_keeps_answers(self):
        """«Отправить» без предварительного «Сохранить» — ответы не теряются."""
        task = self.tasks[0]
        task.answer_mask = '{{equation: x=2}}'
        task.save()
        self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': 'ответ без черновика'})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_SUBMITTED)
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        self.assertEqual(submission.answer_json['s1'], 'ответ без черновика')

    def test_submit_without_draft_keeps_subitem_answers(self):
        item = self.assignment.worksheet.ordered_items()[0]
        task = item.task
        s1 = TaskSubitem.objects.create(task=task, order=10, text_latex='$1+1$', answer_mask='{{number: 2}}')
        self.client.post(
            reverse('submit_assignment', args=[self.assignment.pk]),
            {f'task{task.pk}_sub{s1.pk}_s1': 'два'})
        part = SubmissionPart.objects.get(subitem=s1)
        self.assertEqual(part.answer_json['s1'], 'два')

    def test_photo_actions_keep_unsaved_text(self):
        """Загрузка и удаление фото сохраняют присланные поля ответов."""
        task = self.tasks[0]
        task.answer_mask = '{{equation: x=2}}'
        task.save()
        self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, task.pk]),
            {'photos': fake_photo(), f'task{task.pk}_s1': 'с фото'})
        submission = Submission.objects.get(
            assignment=self.assignment, task=task)
        self.assertEqual(submission.answer_json['s1'], 'с фото')
        photo = SubmissionPhoto.objects.get()
        self.client.post(
            reverse('delete_photo', args=[self.assignment.pk, photo.pk]),
            {f'task{task.pk}_s1': 'после удаления фото'})
        submission.refresh_from_db()
        self.assertEqual(submission.answer_json['s1'], 'после удаления фото')
        self.assertFalse(SubmissionPhoto.objects.exists())

    def test_post_without_answer_fields_does_not_clear(self):
        """POST без полей ответа (форма фото) не затирает сохранённое."""
        task = self.tasks[0]
        task.answer_mask = '{{equation: x=2}}'
        task.save()
        Submission.objects.create(
            assignment=self.assignment, task=task, answer_json={'s1': 'было'})
        self.client.post(
            reverse('upload_photo', args=[self.assignment.pk, task.pk]),
            {'photos': fake_photo()})
        self.assertEqual(
            Submission.objects.get(task=task).answer_json['s1'], 'было')
        # А явно присланная пустая строка — это осознанная очистка
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': ''})
        self.assertEqual(Submission.objects.get(task=task).answer_json['s1'], '')

    def test_save_answers_xhr_returns_json(self):
        task = self.tasks[0]
        task.answer_mask = '{{equation: x=2}}'
        task.save()
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': 'x = 3'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(
            Submission.objects.get(task=task).answer_json['s1'], 'x = 3')
        # После отправки автосохранение получает JSON-отказ, а не HTML 403
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': 'поздно'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assertEqual(
            Submission.objects.get(task=task).answer_json['s1'], 'x = 3')

    def test_assignment_form_has_autosave(self):
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'data-autosave="change"')

    def test_task_without_answer_input_has_no_explanatory_placeholder(self):
        task = self.tasks[0]
        task.full_answer_only = True
        task.save(update_fields=['full_answer_only'])
        self.assignment.allow_photos = False
        self.assignment.save(update_fields=['allow_photos'])

        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))

        self.assertNotContains(
            response, 'Ввод ответа для этой задачи пока не настроен')

    def test_strict_masks_use_math_keyboard_for_student(self):
        task = self.tasks[0]
        task.answer_mask = (
            '{{digits: 234}} {{decimal: -0,5}} '
            '{{ratio: 1:2}} {{proportion: 1:2}}')
        task.save(update_fields=['answer_mask'])

        response = self.client.get(reverse(
            'assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'data-mask-format=', count=4)
        for kind in ('digits', 'decimal', 'ratio', 'proportion'):
            self.assertContains(response, f'data-mask-format="{kind}"')
        self.assertContains(response, 'mathlive.min.js')

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

    def test_dashboard_prioritizes_returned_then_overdue(self):
        self.assignment.due_at = timezone.now() + timedelta(days=2)
        self.assignment.save()
        overdue = make_assignment(
            self.teacher, self.student,
            due_at=timezone.now() - timedelta(days=1))
        returned = make_assignment(
            self.teacher, self.student, status=Assignment.STATUS_RETURNED)

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(
            response.context['todo'],
            [returned, overdue, self.assignment])
        self.assertEqual(response.context['current'], returned)

    def test_formula_mask_preserves_long_latex(self):
        """Формула хранится в слоте без ограничения длины; пустой ввод очищает слот."""
        task = self.tasks[0]
        task.answer_mask = '{{simplify: x+1}}'
        task.save()
        value = r'\left(x+1\right)' * 20
        field = f'task{task.pk}_s1'
        url = reverse('save_answers', args=[self.assignment.pk])
        self.client.post(url, {field: value})
        self.assertEqual(Submission.objects.get(task=task).answer_json['s1'], value)
        response = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, '<math-field')
        self.client.post(url, {field: ''})
        self.assertEqual(Submission.objects.get(task=task).answer_json['s1'], '')

    def test_long_historical_interval_is_readable(self):
        task = self.tasks[0]
        value = r'\left(-\infty; 3\right]' * 20
        submission = Submission.objects.create(assignment=self.assignment, task=task,
                                                interval_low=value, interval_high=value)
        self.assertIn(value, submission.legacy_answer)
        self.assertGreater(len(submission.legacy_answer), 64)

    def test_mask_renders_controls_and_legacy_readonly(self):
        """С маской ученик видит контролы по слотам (simplify — math-field),
        без маски — только действие загрузки фото; старый свободный ответ после
        сдачи показывается как есть."""
        task = self.tasks[0]
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, f'name="task{task.pk}_text"')
        self.assertNotContains(response, 'mask-photo-note')
        task.answer_mask = r'Упростите: {{simplify: \frac{2}{a+3}}}'
        task.save()
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, 'mask-answer')
        self.assertContains(response, '<math-field')
        self.assertContains(response, f'name="task{task.pk}_s1"')
        self.assertContains(response, 'mathlive')
        self.assertNotContains(response, 'mask-photo-note')
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

    def test_range_and_order_widgets_markup(self):
        """У слота range — контейнер числовой прямой, у order — список и
        селекты позиций (виджеты дорисовывает JS); после сдачи — только текст."""
        task = self.tasks[0]
        task.answer_mask = r'{{range: (-\infty; -5) \cup [1; 4)}} и {{order: 1|2|3}}'
        task.save()
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, f'data-numberline="task{task.pk}_s1"')
        self.assertContains(response, f'data-mirror="task{task.pk}_s1"')
        self.assertContains(response, 'js/numberline.js')
        self.assertContains(response, 'data-mask-order')
        self.assertContains(response, f'name="task{task.pk}_s2_0"')
        from .checks import parse_mask
        order_slot = [s for s in parse_mask(task.answer_mask).slots
                      if s.kind == 'order'][0]
        tokens = order_slot.order_tokens(f'task{task.pk}')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{task.pk}_s1': r'(-\infty; -5) \cup [1; 4)',
             f'task{task.pk}_s2_0': tokens[0],
             f'task{task.pk}_s2_1': tokens[1],
             f'task{task.pk}_s2_2': tokens[2]})
        submission = Submission.objects.get(task=task)
        self.assertEqual(submission.check_json, {'s1': 'ok', 's2': 'ok'})
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        response = self.client.get(
            reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertNotContains(response, 'data-numberline')
        self.assertContains(response, r'(-\infty; -5)')

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
        self.assertRedirects(response, reverse('assignment_list'))
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

    def test_complete_and_open_next_pending(self):
        self.assignment.refresh_from_db()
        make_assignment(
            self.teacher, self.student,
            status=Assignment.STATUS_SUBMITTED,
            submitted_at=self.assignment.submitted_at - timedelta(minutes=1))
        next_assignment = make_assignment(
            self.teacher, self.student,
            status=Assignment.STATUS_SUBMITTED,
            submitted_at=timezone.now() + timedelta(minutes=1))
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        response = self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                f'sub{submission.pk}_comment': '',
                'action': 'complete_next',
            })
        self.assertRedirects(
            response, reverse('review_assignment', args=[next_assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_REVIEWED)

    def test_return_and_open_next_pending(self):
        next_assignment = make_assignment(
            self.teacher, self.student,
            status=Assignment.STATUS_SUBMITTED,
            submitted_at=timezone.now() + timedelta(minutes=1))
        response = self.client.post(
            reverse('save_review', args=[self.assignment.pk]), {
                'action': 'return_next',
            })
        self.assertRedirects(
            response, reverse('review_assignment', args=[next_assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_RETURNED)

    def test_review_form_has_clickable_grade_scale(self):
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, 'data-grade="="')
        self.assertNotContains(response, 'data-review-done')
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
        self.task.answer_mask = '{{set: 0; 2}}'
        self.task.save()
        submission.answer_json = {'s1': '2; 0'}
        submission.run_check(spec=self.task.mask_spec)
        submission.save()
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertTrue(response.context['rows'][0]['auto_ok'])
        self.assertNotContains(response, 'data-review-done')
        self.assertContains(response, 'data-grade="+"')

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
        self.assertRedirects(response, reverse('assignment_list'))
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

    def test_check_after_reference_change_with_unavailable_checker_reveals_nothing(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{expression: a+29}}'
        self.task.save()
        formulas._checked.cache_clear()
        self._save('29+a')
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        # Учитель поправил эталон — сверка устарела; ученик жмёт «Проверить»
        # с тем же ответом, а вычислитель недоступен: прежний вердикт по
        # старому эталону не раскрывается и попытка не списывается.
        self.task.answer_mask = '{{expression: a+30}}'
        self.task.save()
        formulas._checked.cache_clear()
        formulas._failed_inputs.clear()
        with mock.patch.object(formulas, '_run_worker',
                               side_effect=subprocess.TimeoutExpired('worker', 3)):
            response = self._check('29+a')
        self.assertFalse(response.json()['ok'])
        self.assertIn('временно недоступна', response.json()['message'])
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, '')
        self.assertIsNone(submission.checked_at)
        self.assertFalse(submission.check_revealed)
        self.assertFalse(SubmissionCheckAttempt.objects.exists())

    def test_cooldown_does_not_spend_retry_or_student_attempt(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{expression: a+151}}'
        self.task.save()
        formulas._checked.cache_clear()
        formulas._failed_inputs.clear()
        self.addCleanup(formulas._failed_inputs.clear)
        with mock.patch.object(formulas.subprocess, 'run',
                               side_effect=subprocess.TimeoutExpired('worker', 3)) as worker:
            self._save('151+a')
            response = self._check('151+a')
            self._save('151+a')
            worker.assert_called_once()
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.check_json, {formulas.UNAVAILABLE_KEY: 1})
        self.assertEqual(submission.auto_check, '')
        self.assertIsNone(submission.checked_at)
        self.assertFalse(response.json()['ok'])
        self.assertFalse(submission.check_revealed)
        self.assertFalse(SubmissionCheckAttempt.objects.exists())
        # После паузы действительно запускается повторная проверка.
        formulas._failed_inputs.clear()
        response = self._check('151+a')
        self.assertEqual(response.json()['checks'],
                         {f'task{self.task.pk}': 'ok', self.field: 'ok'})
        self.assertEqual(SubmissionCheckAttempt.objects.count(), 1)

    def test_manual_result_does_not_expose_internal_failure_counter(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{expression: a+157}}'
        self.task.save()
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker',
                               side_effect=formulas.FormulaUnavailable('сбой')):
            self._save('157+a')
            response = self._check('157+a')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['checks'], {f'task{self.task.pk}': 'unknown', self.field: 'unknown'})
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.check_json, {'s1': 'unknown', formulas.UNAVAILABLE_KEY: 2})

    def test_failure_limit_preserves_slots_and_latches_until_answer_or_reference_changes(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{number: 4}} {{expression: a+181}} {{number: 7}}'
        self.task.save()
        formulas._checked.cache_clear()
        data = {self.field: '4', f'task{self.task.pk}_s2': '181+a', f'task{self.task.pk}_s3': '8'}
        with mock.patch.object(formulas, '_run_worker', side_effect=formulas.FormulaUnavailable('сбой')) as worker:
            self.client.post(self.url, data)
            self.client.post(self.url, data)
            self.assertEqual(worker.call_count, 2)
            # Неизменное автосохранение и кнопка проверки уже не вычисляют.
            self.client.post(self.url, data)
            response = self.client.post(reverse('check_task', args=[self.assignment.pk, self.task.pk]),
                                        data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(worker.call_count, 2)
        checks = response.json()['checks']
        self.assertEqual([checks[f'task{self.task.pk}_s{i}'] for i in (1, 2, 3)], ['ok', 'unknown', 'wrong'])
        # Изменённый ввод возвращает право на вычисление.
        data[f'task{self.task.pk}_s2'] = 'a+182'
        with mock.patch.object(formulas, '_run_worker', side_effect=formulas.FormulaUnavailable('сбой')) as worker:
            self.client.post(self.url, data)
            self.client.post(self.url, data)
            self.assertEqual(worker.call_count, 2)
        # Новый эталон тоже отменяет старый окончательный unknown.
        self.task.answer_mask = '{{number: 4}} {{expression: a+182}} {{number: 8}}'
        self.task.save()
        self.client.post(self.url, data)
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.assertNotIn(formulas.UNAVAILABLE_KEY, submission.check_json)

    def test_legacy_empty_verdict_is_not_reported_as_temporary_failure(self):
        submission = Submission.objects.create(assignment=self.assignment, task=self.task,
                                               answer_text='свободный исторический ответ')
        response = self._check()
        self.assertTrue(response.json()['ok'])
        self.assertNotIn('временно недоступна', response.json()['message'])
        submission.refresh_from_db()
        self.assertTrue(submission.check_revealed)

    def test_editing_failed_formula_rechecks_other_previously_skipped_formulas(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{expression: a+197}} {{expression: b+199}}'
        self.task.save()
        formulas._checked.cache_clear()
        data = {self.field: '197+a', f'task{self.task.pk}_s2': '199+b'}
        with mock.patch.object(formulas, '_run_worker', side_effect=formulas.FormulaUnavailable('сбой')) as worker:
            self.client.post(self.url, data)
            self.client.post(self.url, data)
            # На каждом сбое вторая формула пропущена, а не вычислена.
            self.assertEqual(worker.call_count, 2)
        data[self.field] = 'a+197'
        with mock.patch.object(formulas, '_run_worker', wraps=formulas._run_worker) as worker:
            self.client.post(self.url, data)
            self.assertEqual(worker.call_count, 2)
        submission = Submission.objects.get(assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')
        self.assertEqual(submission.check_json, {'s1': 'ok', 's2': 'ok'})

    def test_selected_unmasked_subitem_is_not_a_temporary_failure(self):
        a = TaskSubitem.objects.create(task=self.task, order=1, text_latex='а')
        TaskSubitem.objects.create(task=self.task, order=2, text_latex='б', answer_mask='{{number: 2}}')
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        part = SubmissionPart.objects.create(submission=submission, subitem=a, answer_text='свободный ответ')
        response = self.client.post(reverse('check_task', args=[self.assignment.pk, self.task.pk]),
                                    {'check_subitem': str(a.pk)}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['ok'])
        self.assertNotIn('временно недоступна', response.json()['message'])
        part.refresh_from_db()
        self.assertTrue(part.check_revealed)

    def test_changed_reference_on_page_resets_limit_once_and_hides_old_verdict(self):
        from assignments.checks import formulas
        self._save('0; 2')
        self.task.answer_mask = '{{expression: a+193}}'
        self.task.save()
        with mock.patch.object(formulas, '_run_worker', side_effect=formulas.FormulaUnavailable('сбой')) as worker:
            self.client.get(self.detail)
            submission = Submission.objects.get(assignment=self.assignment, task=self.task)
            self.assertEqual(submission.auto_check, '')
            self.assertIsNone(submission.checked_at)
            self.client.get(self.detail)
            self.client.get(self.detail)
            self.assertEqual(worker.call_count, 2)
        submission.refresh_from_db()
        self.assertEqual(submission.auto_check, 'unknown')
        self.assertEqual(submission.check_json, {'s1': 'unknown', formulas.UNAVAILABLE_KEY: 2})

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
        self.assignment.check_visibility = Assignment.CHECK_TEACHER
        self.assignment.save()
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
        first_attempt = submission.check_history.get(number=1)
        self.assertEqual(first_attempt.result, SubmissionCheckAttempt.RESULT_WRONG)
        self.assertEqual(first_attempt.snapshot['targets'][0]['answer'],
                         'Корни: [7]')
        self.assertEqual(first_attempt.snapshot['targets'][0]['slots'], [{
            'name': 's1', 'label': 'конечное множество чисел',
            'value': '7', 'result': 'wrong',
        }])
        # Новый ответ — бейдж прячется до следующего нажатия
        self._save('0; 2')
        self.assertNotContains(self.client.get(self.detail), 'верно</span>')
        self._check()
        self.assertContains(self.client.get(self.detail), '✓ верно')
        submission.refresh_from_db()
        self.assertEqual(submission.check_attempts, 2)
        self.assertEqual(submission.check_history.count(), 2)
        first_attempt.refresh_from_db()
        self.assertEqual(first_attempt.snapshot['targets'][0]['answer'],
                         'Корни: [7]')
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
        self.assertFalse(SubmissionCheckAttempt.objects.exists())

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
        # У задачи с подпунктами хватает маски хотя бы на одном подпункте
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
        attempt = submission.check_history.get()
        self.assertEqual(attempt.result, SubmissionCheckAttempt.RESULT_WRONG)
        self.assertEqual(
            [target['result'] for target in attempt.snapshot['targets']],
            ['ok', 'wrong'])

    def test_each_subitem_has_own_check_button_and_result(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        a = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='а', answer_mask='{{number: 1}}')
        b = TaskSubitem.objects.create(
            task=self.task, order=2, text_latex='б', answer_mask='{{number: 2}}')
        response = self.client.get(self.detail)
        self.assertContains(response, 'name="check_subitem"', count=2)
        self.assertContains(response, f'value="{a.pk}"')
        self.assertContains(response, f'value="{b.pk}"')

        response = self.client.post(
            reverse('check_task', args=[self.assignment.pk, self.task.pk]),
            {
                'check_subitem': str(a.pk),
                f'task{self.task.pk}_sub{a.pk}_s1': '1',
                f'task{self.task.pk}_sub{b.pk}_s1': '3',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['checks'], {
            f'task{self.task.pk}_sub{a.pk}': 'ok',
            f'task{self.task.pk}_sub{a.pk}_s1': 'ok',
        })
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        parts = {part.subitem_id: part for part in submission.parts.all()}
        self.assertTrue(parts[a.pk].check_revealed)
        self.assertFalse(parts[b.pk].check_revealed)
        attempt = submission.check_history.get()
        self.assertEqual(attempt.result, SubmissionCheckAttempt.RESULT_OK)
        self.assertEqual(
            [target['id'] for target in attempt.snapshot['targets']], [a.pk])

    def test_check_rejects_subitem_from_another_task(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        foreign = TaskSubitem.objects.create(
            task=Task.objects.create(text_latex='Чужая задача'),
            order=1, text_latex='а', answer_mask='{{number: 1}}')
        response = self.client.post(
            reverse('check_task', args=[self.assignment.pk, self.task.pk]),
            {'check_subitem': str(foreign.pk)})
        self.assertEqual(response.status_code, 404)

    def test_partial_subitems_are_recorded_as_incomplete(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        a = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='а', answer_mask='{{number: 1}}')
        TaskSubitem.objects.create(
            task=self.task, order=2, text_latex='б', answer_mask='{{number: 2}}')
        self.client.post(
            reverse('check_task', args=[self.assignment.pk, self.task.pk]),
            {f'task{self.task.pk}_sub{a.pk}_s1': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        attempt = SubmissionCheckAttempt.objects.get()
        self.assertEqual(
            attempt.result, SubmissionCheckAttempt.RESULT_INCOMPLETE)
        self.assertEqual(len(attempt.snapshot['targets']), 2)
        self.assertEqual(attempt.snapshot['targets'][1]['answer'], '')

    def test_review_shows_attempt_history_and_legacy_count(self):
        self.assignment.check_visibility = Assignment.CHECK_LIVE
        self.assignment.save()
        self._check('7')
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        submission.check_attempts = 3
        submission.save(update_fields=['check_attempts'])
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, 'Самопроверка — нажатий: 3')
        self.assertContains(response, 'Попытка 1')
        self.assertContains(response, 'Ранних попыток без сохранённого ответа: 2')

    def test_auto_ok_requires_every_subitem(self):
        a = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='а', answer_latex='1', answer_mask='{{number: 1}}')
        b = TaskSubitem.objects.create(
            task=self.task, order=2, text_latex='б', answer_latex='2', answer_mask='{{number: 2}}')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{self.task.pk}_sub{a.pk}_s1': '1'})
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(
            reverse('review_assignment', args=[self.assignment.pk]))
        self.assertFalse(response.context['rows'][0]['auto_ok'])
        self.client.login(username='student1', password='pass12345')
        self.client.post(
            reverse('save_answers', args=[self.assignment.pk]),
            {f'task{self.task.pk}_sub{a.pk}_s1': '1',
             f'task{self.task.pk}_sub{b.pk}_s1': '2'})
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

    def test_review_hides_stale_verdict_without_recomputing(self):
        self._save('0; 2')
        self.client.post(reverse('submit_assignment', args=[self.assignment.pk]))
        self.client.login(username='teacher1', password='pass12345')
        review_url = reverse('review_assignment', args=[self.assignment.pk])
        self.assertContains(self.client.get(review_url), 'class="mask-value" data-status="ok"')
        # Учитель исправил маску — старый вердикт скрыт без вычислений
        self.task.answer_mask = 'Корни: {{set: 1; 3}}'
        self.task.save()
        response = self.client.get(review_url)
        self.assertContains(response, 'class="mask-value" data-status=""')
        self.assertContains(response, 'Сверка требует обновления')
        self.assertFalse(response.context['rows'][0]['auto_ok'])
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.auto_check, 'ok')

    def test_teacher_does_not_compute_stale_task_or_subitem_or_consume_limit(self):
        from assignments.checks import formulas
        for subitem in (False, True):
            with self.subTest(subitem=subitem):
                self.task.answer_mask = '{{expression: a+211}}'
                self.task.save()
                submission, _ = Submission.objects.get_or_create(
                    assignment=self.assignment, task=self.task)
                if subitem:
                    part = TaskSubitem.objects.create(task=self.task, order=1,
                        text_latex='а', answer_mask='{{expression: b+223}}')
                    obj = SubmissionPart.objects.create(submission=submission, subitem=part)
                else:
                    obj = submission
                obj.answer_json = {'s1': '211+a'}
                obj.check_json = {formulas.UNAVAILABLE_KEY: 1}
                obj.save()
                self.client.force_login(self.teacher)
                with mock.patch.object(formulas, '_run_worker') as worker:
                    for _ in range(2):
                        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
                        self.assertContains(response, 'Сверка требует обновления')
                    live = self.client.get(reverse('assignment_live', args=[self.assignment.pk]))
                    self.assertIn('Сверка требует обновления', ''.join(live.json()['rows'].values()))
                    worker.assert_not_called()
                obj.refresh_from_db()
                self.assertEqual(obj.check_json, {formulas.UNAVAILABLE_KEY: 1})
                self.assertIsNone(obj.checked_at)

    def test_student_refreshes_one_answer_across_subitems_and_tasks(self):
        from assignments.checks import formulas
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        parts = []
        for i, value in enumerate((227, 229), start=1):
            subitem = TaskSubitem.objects.create(task=self.task, order=i,
                text_latex='а', answer_mask='{{expression: a+' + str(value) + '}}')
            parts.append(SubmissionPart.objects.create(submission=submission, subitem=subitem,
                answer_json={'s1': str(value) + '+a'}, check_revealed=True))
        extra = Task.objects.create(text_latex='Другой ответ', answer_mask='{{expression: b+233}}')
        WorksheetItem.objects.create(worksheet=self.assignment.worksheet, task=extra, order=50)
        other = Submission.objects.create(assignment=self.assignment, task=extra,
            answer_json={'s1': '233+b'}, check_revealed=True, auto_check='wrong',
            check_json={'s1': 'wrong'}, checked_at=extra.updated_at - timedelta(seconds=1))
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker', wraps=formulas._run_worker) as worker:
            response = self.client.get(self.detail)
            self.assertEqual(worker.call_count, 1)
            # Пропущенный старый вердикт скрыт только в представлении.
            self.assertEqual(response.context['rows'][-1]['submission'].student_check, '')
            parts[0].refresh_from_db(); parts[1].refresh_from_db(); other.refresh_from_db()
            self.assertEqual(parts[0].auto_check, 'ok')
            self.assertIsNone(parts[1].checked_at)
            self.assertEqual(other.auto_check, 'wrong')
            self.client.get(self.detail)
            self.assertEqual(worker.call_count, 2)
            self.client.get(self.detail)
            self.assertEqual(worker.call_count, 3)
        other.refresh_from_db()
        self.assertEqual(other.auto_check, 'ok')

    def test_student_refresh_does_not_wait_for_busy_formula_slot(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{expression: a+239}}'
        self.task.save()
        submission = Submission.objects.create(assignment=self.assignment, task=self.task,
            answer_json={'s1': '239+a'})
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_worker_slots') as slots:
            slots.acquire.return_value = False
            self.assertEqual(self.client.get(self.detail).status_code, 200)
            slots.acquire.assert_called_once_with(timeout=0)
        submission.refresh_from_db()
        self.assertEqual(submission.check_json, {formulas.UNAVAILABLE_KEY: 0})
        self.assertIsNone(submission.checked_at)

    def test_refresh_skips_legacy_answer_and_checks_mask_answer(self):
        """Исторический текст без значений маски не занимает слот бюджета."""
        from assignments.checks import formulas
        self.assignment.check_visibility = Assignment.CHECK_TEACHER
        self.assignment.save()
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        legacy_item = TaskSubitem.objects.create(task=self.task, order=1,
            text_latex='а', answer_mask='{{number: 5}}')
        legacy = SubmissionPart.objects.create(submission=submission, subitem=legacy_item,
            answer_text='5')
        masked_item = TaskSubitem.objects.create(task=self.task, order=2,
            text_latex='б', answer_mask='{{expression: a+311}}')
        masked = SubmissionPart.objects.create(submission=submission, subitem=masked_item,
            answer_json={'s1': '311+a'})
        self.client.force_login(self.teacher)
        review_url = reverse('review_assignment', args=[self.assignment.pk])
        refresh_url = reverse('refresh_assignment_check', args=[self.assignment.pk])
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker', wraps=formulas._run_worker) as worker:
            self.assertRedirects(self.client.post(refresh_url), review_url)
            self.assertEqual(worker.call_count, 1)
        masked.refresh_from_db(); legacy.refresh_from_db()
        self.assertEqual(masked.auto_check, 'ok')
        self.assertIsNotNone(masked.checked_at)
        self.assertIsNone(legacy.checked_at)
        self.assertNotContains(self.client.get(review_url), 'Обновить сверку')

    def test_teacher_explicitly_refreshes_one_answer_in_hidden_mode(self):
        from assignments.checks import formulas
        self.assignment.check_visibility = Assignment.CHECK_TEACHER
        self.assignment.save()
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        parts = []
        for i, value in enumerate((257, 263), start=1):
            subitem = TaskSubitem.objects.create(task=self.task, order=i,
                text_latex='а', answer_mask='{{expression: a+' + str(value) + '}}')
            parts.append(SubmissionPart.objects.create(submission=submission, subitem=subitem,
                answer_json={'s1': str(value) + '+a'}))
        self.client.force_login(self.teacher)
        review_url = reverse('review_assignment', args=[self.assignment.pk])
        refresh_url = reverse('refresh_assignment_check', args=[self.assignment.pk])
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker', wraps=formulas._run_worker) as worker:
            self.assertContains(self.client.get(review_url), 'Обновить сверку')
            worker.assert_not_called()
            self.assertRedirects(self.client.post(refresh_url), review_url)
            self.assertEqual(worker.call_count, 1)
            parts[0].refresh_from_db(); parts[1].refresh_from_db()
            self.assertEqual(parts[0].auto_check, 'ok')
            self.assertIsNone(parts[1].checked_at)
            self.assertContains(self.client.get(review_url), 'Обновить сверку')
            self.client.post(refresh_url)
            self.assertEqual(worker.call_count, 2)
        self.assertNotContains(self.client.get(review_url), 'Обновить сверку')
        self.assertFalse(Review.objects.filter(submission=submission).exists())
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.STATUS_ASSIGNED)

    def test_hidden_student_check_refreshes_without_revealing_result(self):
        from assignments.checks import formulas
        self.assignment.check_visibility = Assignment.CHECK_TEACHER
        self.assignment.save()
        self.task.answer_mask = '{{expression: a+269}}'
        self.task.save()
        obj = Submission.objects.create(assignment=self.assignment, task=self.task,
            answer_json={'s1': '269+a'}, check_revealed=True)
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker', wraps=formulas._run_worker) as worker:
            response = self.client.get(self.detail)
            self.assertEqual(worker.call_count, 1)
        obj.refresh_from_db()
        self.assertEqual(obj.auto_check, 'ok')
        self.assertEqual(obj.student_check, '')
        self.assertEqual(obj.student_slot_checks, {})
        self.assertNotContains(response, '✓ верно')
        self.assignment.status = Assignment.STATUS_SUBMITTED
        self.assignment.save()
        response = self.client.get(self.detail)
        self.assertNotContains(response, 'data-status="ok"')

    def test_explicit_refresh_has_teacher_ownership_and_post_guards(self):
        refresh_url = reverse('refresh_assignment_check', args=[self.assignment.pk])
        self.assertEqual(self.client.post(refresh_url).status_code, 403)
        other = make_teacher('other_refresh_teacher')
        self.client.force_login(other)
        self.assertEqual(self.client.post(refresh_url).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(refresh_url).status_code, 405)

    def test_refresh_does_not_overwrite_new_answer_saved_during_computation(self):
        from assignments.checks import formulas
        self.task.answer_mask = '{{expression: a+271}}'
        self.task.save()
        obj = Submission.objects.create(assignment=self.assignment, task=self.task,
            answer_json={'s1': '271+a'})
        original = formulas._run_worker
        def save_new_answer(*args, **kwargs):
            Submission.objects.filter(pk=obj.pk).update(answer_json={'s1': '272+a'},
                auto_check='wrong', check_json={'s1': 'wrong'}, checked_at=timezone.now())
            return original(*args, **kwargs)
        formulas._checked.cache_clear()
        with mock.patch.object(formulas, '_run_worker', side_effect=save_new_answer):
            self.client.get(self.detail)
        obj.refresh_from_db()
        self.assertEqual(obj.answer_json, {'s1': '272+a'})
        self.assertEqual(obj.auto_check, 'wrong')
        self.assertEqual(obj.check_json, {'s1': 'wrong'})

    def test_review_shows_filled_mask_with_result_and_reference(self):
        """Учителю — заполненная маска, цвета полей и авторский ответ;
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
        self.assertNotContains(response, 'check-badge')
        self.assertContains(response, 'class="mask-value" data-status="ok"', count=2)
        self.assertContains(response, 'Ответ:')
        self.assertContains(response, '0; 2')
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
        self.assertContains(response, 'Редактировать назначения')
        response = self.client.get(reverse('assignment_create'), {'worksheet': worksheet.pk})
        self.assertTrue(response.context['form'].fields['check_visibility'].disabled)
        self.assertEqual(response.context['form'].fields['check_visibility'].initial, 'live')
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
                         Assignment.CHECK_LIVE)

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
        """Ответ, сданный до появления маски, сохраняет старую оценку и
        показывается учителю; заполненные слоты имеют приоритет."""
        self.task.answer_mask = ''
        self.task.answer_latex = r'\frac{1}{4}'
        self.task.save()
        Submission.objects.create(assignment=self.assignment, task=self.task,
                                  answer_text='0,25', answer_number='0,25', auto_check='ok')
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
        self.task.answer_latex = r'\frac{1}{4}'
        self.task.save()
        Submission.objects.create(assignment=self.assignment, task=self.task,
                                  answer_text='0,25', answer_number='0,25', auto_check='ok')
        self.task.answer_mask = '{{number: 5}}'
        self.task.save()
        response = self.client.get(self.detail)
        self.assertContains(response, '0,25')
        self.assertContains(response, f'name="task{self.task.pk}_s1"')

    def test_no_mask_does_not_accept_old_free_fields(self):
        """Без маски нельзя обойти новую форму отправкой старых полей."""
        self.task.answer_mask = ''
        self.task.save()
        self.assignment.allow_photos = False
        self.assignment.save()
        field = f'task{self.task.pk}_text'
        response = self.client.get(self.detail)
        self.assertNotContains(response, f'name="{field}"')
        self.client.post(self.url, {field: 'разбор на бумаге'})
        self.assertFalse(Submission.objects.filter(assignment=self.assignment, task=self.task).exists())

    def test_cleared_order_slot_is_saved(self):
        self.task.answer_mask = '{{order: a|b}}'
        self.task.save()
        self.client.post(self.url, order_form(self.task, 0, 1))
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.answer_json, {'s1': '0|1'})
        self.client.post(self.url, order_form(self.task, None, None))
        submission.refresh_from_db()
        self.assertEqual(submission.answer_json.get('s1'), '')

    def test_partial_order_is_restored(self):
        self.task.answer_mask = '{{order: a|b|c}}'
        self.task.save()
        self.client.post(self.url, order_form(self.task, 0, None, None))
        submission = Submission.objects.get(
            assignment=self.assignment, task=self.task)
        self.assertEqual(submission.answer_json, {'s1': '0||'})
        response = self.client.get(self.detail)
        self.assertContains(response, f'name="task{self.task.pk}_s1_0"')
        html = response.content.decode()
        from .checks import parse_mask
        token = parse_mask(self.task.answer_mask).slots[0].order_tokens(
            f'task{self.task.pk}')[0]
        self.assertRegex(
            html,
            rf'name="task{self.task.pk}_s1_0"[^>]*>[\s\S]*?'
            rf'<option value="{token}" selected')
        self.assertNotRegex(html, r'data-index="\d+"')
        self.assertNotRegex(html, r'<option value="\d+"')
        self.client.post(self.url, {
            f'task{self.task.pk}_s1_0': '0',
            f'task{self.task.pk}_s1_1': '1',
            f'task{self.task.pk}_s1_2': '2',
        })
        submission.refresh_from_db()
        self.assertNotEqual(submission.answer_json.get('s1'), '0|1|2')


class NumberLineJsTests(SimpleTestCase):
    def test_format_latex_decimal_roundtrip(self):
        """parse(formatLatex([{lo:1.5,...}])) не должен ломаться на 1{,}5."""
        node = shutil.which('node')
        if not node:
            self.skipTest('node не установлен')
        js = Path(__file__).resolve().parents[1] / 'static/js/numberline.js'
        script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {window: {}, document: {createElementNS: function () { return {}; }, addEventListener: function () {}}};
vm.runInNewContext(src, ctx);
const NL = ctx.window.EgorNumberLine;
const text = NL.formatLatex([{lo: 1.5, hi: 4, lc: true, rc: true}]);
if (text.indexOf('{,}') < 0) process.exit(2);
const parsed = NL.parse(text);
if (!parsed || parsed.length !== 1) process.exit(3);
if (parsed[0].lo !== 1.5 || parsed[0].hi !== 4 || !parsed[0].lc || !parsed[0].rc)
  process.exit(4);
if (NL.num('1{,}5') !== 1.5 || NL.parse('[1.5; 4]') === null) process.exit(5);
const points = [
  {lo: -2, hi: -2, lc: true, rc: true},
  {lo: 1, hi: 1, lc: true, rc: true},
  {lo: 3, hi: 3, lc: true, rc: true},
];
const pointText = NL.formatLatex(points);
if (pointText !== '\\{-2; 1; 3\\}') process.exit(6);
const pointParsed = NL.parse(pointText);
if (!pointParsed || pointParsed.length !== 3
    || pointParsed.some(iv => iv.lo !== iv.hi || !iv.lc || !iv.rc)) process.exit(7);
if (NL.format(points) !== '{-2; 1; 3}') process.exit(8);
const mixed = NL.formatLatex(points.slice(0, 1).concat([
  {lo: 1, hi: 4, lc: true, rc: false},
]));
if (mixed !== '\\{-2\\} \\cup [1; 4)') process.exit(9);
const mixedParsed = NL.parse(mixed);
if (!mixedParsed || mixedParsed.length !== 2) process.exit(10);
"""
        subprocess.check_call([node, '-e', script, str(js)])


class MaskJsTests(SimpleTestCase):
    def test_mathlive_strict_value_normalizes_only_serialization(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node не установлен')
        js = Path(__file__).resolve().parents[1] / 'static/js/mask.js'
        script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {window: {}, document: {addEventListener: function () {}}};
vm.runInNewContext(src, ctx);
const value = ctx.window.EgorMask.value;
function field(text, kind) { return {value: text, dataset: {maskFormat: kind}}; }
if (value(field('-0{,}5', 'decimal')) !== '-0,5') process.exit(2);
if (value(field('1\\colon 2', 'ratio')) !== '1:2') process.exit(3);
if (value(field('2 3 4', 'digits')) !== '2 3 4') process.exit(4);
if (value({value: '\\frac{1}{2}', dataset: {}}) !== '\\frac{1}{2}') process.exit(5);
"""
        subprocess.check_call([node, '-e', script, str(js)])
