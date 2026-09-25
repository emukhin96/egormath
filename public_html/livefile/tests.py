"""Файлы-версии живых страниц и сравнение ETag с суффиксом Apache."""
import json
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from assignments.models import Assignment
from canvas.models import CanvasPage
from independentworks.models import Candidate, Position, Work
from independentworks import services as iw
from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet

from . import etags, files


class LiveFileBase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(LIVE_FILE_DIR=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

    def stamp(self, kind, *ids):
        path = files.path(kind, *ids)
        return path.read_text() if path.exists() else None


class FilesTests(LiveFileBase):
    def test_token_is_stable_hex_and_differs_by_key(self):
        self.assertEqual(files.token('run', 5), files.token('run', 5))
        self.assertEqual(len(files.token('run', 5)), 32)
        self.assertTrue(all(c in '0123456789abcdef' for c in files.token('run', 5)))
        self.assertNotEqual(files.token('run', 5), files.token('run', 6))
        self.assertNotEqual(files.token('run', 5), files.token('assignment', 5))
        self.assertNotEqual(files.token('board', 1, 2), files.token('board', 12))

    def test_url_creates_file_once(self):
        url = files.url('worksheet', 7)
        self.assertEqual(url, f'/live/{files.token("worksheet", 7)}.txt')
        first = self.stamp('worksheet', 7)
        self.assertTrue(first)
        files.url('worksheet', 7)
        self.assertEqual(self.stamp('worksheet', 7), first, 'повторный url() не перезаписывает файл')

    def test_touch_rewrites_after_commit(self):
        files.url('run', 1)
        before = self.stamp('run', 1)
        with self.captureOnCommitCallbacks(execute=True):
            files.touch('run', 1)
            self.assertEqual(self.stamp('run', 1), before, 'до commit файл не меняется')
        self.assertNotEqual(self.stamp('run', 1), before)
        self.assertEqual([p.name for p in files.directory().iterdir() if p.name.endswith('.tmp')], [])

    def test_serve_view(self):
        self.assertEqual(self.client.get(f'/live/{files.token("run", 1)}.txt').status_code, 404)
        self.assertEqual(self.client.get('/live/not-a-token.txt').status_code, 404)
        files.url('run', 1)
        response = self.client.get(files.url('run', 1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), self.stamp('run', 1))
        self.assertIn('no-cache', response['Cache-Control'])


class EtagTests(TestCase):
    def request(self, header):
        return RequestFactory().get('/', HTTP_IF_NONE_MATCH=header) if header is not None else RequestFactory().get('/')

    def test_matches_plain_gzip_suffix_weak_and_lists(self):
        etag = '"abc123"'
        self.assertTrue(etags.matches(self.request('"abc123"'), etag))
        self.assertTrue(etags.matches(self.request('"abc123"-gzip'), etag), 'mod_deflate дописывает -gzip')
        self.assertTrue(etags.matches(self.request('W/"abc123"'), etag))
        self.assertTrue(etags.matches(self.request('"other", "abc123"-gzip'), etag))
        self.assertTrue(etags.matches(self.request('*'), etag))
        self.assertFalse(etags.matches(self.request('"abc124"-gzip'), etag))
        self.assertFalse(etags.matches(self.request(''), etag))
        self.assertFalse(etags.matches(self.request(None), etag))


class AssignmentSignalTests(LiveFileBase):
    def setUp(self):
        super().setUp()
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.worksheet = make_worksheet(self.teacher)
        self.task = Task.objects.create(text_latex='Сколько будет 2+2?', answer_mask='{{number: 4}}', created_by=self.teacher)
        self.item = WorksheetItem.objects.create(worksheet=self.worksheet, task=self.task, order=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.assignment = Assignment.objects.create(
                worksheet=self.worksheet, student=self.student, assigned_by=self.teacher)
        self.keys = [('assignment', self.assignment.pk), ('worksheet', self.worksheet.pk), ('student', self.student.pk)]
        self.before = {k: self.stamp(*k) for k in self.keys}

    def assert_touched(self, *keys):
        for key in self.keys:
            if key in keys:
                self.assertNotEqual(self.stamp(*key), self.before[key], f'{key} должен измениться')
            else:
                self.assertEqual(self.stamp(*key), self.before[key], f'{key} не должен меняться')

    def test_assignment_creation_touches_all_pages(self):
        for key in self.keys:
            self.assertIsNotNone(self.before[key])

    def test_student_answer_touches_assignment_worksheet_and_student(self):
        self.client.force_login(self.student)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('check_task', args=[self.assignment.pk, self.task.pk]),
                                        {f'task{self.task.pk}_s1': '4'})
        self.assertIn(response.status_code, (200, 302))
        self.assert_touched(*self.keys)

    def test_student_canvas_stroke_does_not_touch_teacher_layer_file(self):
        self.client.force_login(self.student)
        board = ('board', self.assignment.pk, self.task.pk)
        files.url(*board)
        board_before = self.stamp(*board)
        body = {'layer': 'student', 'elements': [{'id': 'a1', 't': 'path', 'c': '#1d4ed8', 'w': 4,
                                                  'p': [[100, 100], [120, 110]]}], 'background': 'grid', 'version': 0}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('canvas:save', args=[self.assignment.pk, self.task.pk, 1]),
                                        data=json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assert_touched(*self.keys)
        self.assertEqual(self.stamp(*board), board_before)
        # Штрих учителя — повод ученику перечитать доску
        page = CanvasPage.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            page.teacher_elements = body['elements']
            page.teacher_version = 1
            page.teacher_updated_at = timezone.now()
            page.save(update_fields=['teacher_elements', 'teacher_version', 'teacher_updated_at'])
        self.assertNotEqual(self.stamp(*board), board_before)

    def test_assignment_status_change_touches_student_boards(self):
        board = ('board', self.assignment.pk, self.task.pk)
        files.url(*board)
        board_before = self.stamp(*board)
        with self.captureOnCommitCallbacks(execute=True):
            self.assignment.status = Assignment.STATUS_RETURNED
            self.assignment.save(update_fields=['status'])
        self.assertNotEqual(self.stamp(*board), board_before, 'права на доске зависят от статуса')

    def test_worksheet_structure_changes_touch_worksheet(self):
        key = ('worksheet', self.worksheet.pk)
        with self.captureOnCommitCallbacks(execute=True):
            second = WorksheetItem.objects.create(worksheet=self.worksheet, task=Task.objects.create(
                text_latex='Ещё задача', created_by=self.teacher), order=2)
        added = self.stamp(*key)
        self.assertNotEqual(added, self.before[key])
        self.client.force_login(self.teacher)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('worksheet_reorder', args=[self.worksheet.pk]),
                                        {'order': f'{second.pk},{self.item.pk}'})
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertNotEqual(self.stamp(*key), added, 'bulk_update порядка идёт мимо сигналов')

    def test_worksheet_progress_fragment_returns_304_with_gzip_suffix(self):
        self.client.force_login(self.teacher)
        url = reverse('worksheet_progress', args=[self.worksheet.pk])
        first = self.client.get(url, {'fragment': 1})
        self.assertEqual(first.status_code, 200)
        again = self.client.get(url, {'fragment': 1}, HTTP_IF_NONE_MATCH=first['ETag'] + '-gzip')
        self.assertEqual(again.status_code, 304)

    def test_progress_page_carries_live_file(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk]))
        self.assertContains(response, f'data-live-file="{files.url("worksheet", self.worksheet.pk)}"')
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(response, f'data-live-file="{files.url("assignment", self.assignment.pk)}"')
        self.client.force_login(self.student)
        response = self.client.get(reverse('assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, f'data-live-file="{files.url("board", self.assignment.pk, self.task.pk)}"')


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class IndependentWorkSignalTests(LiveFileBase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.teacher = User.objects.create_user('teacher')
        Profile.objects.create(user=self.teacher, role='teacher')
        self.student = User.objects.create_user('student')
        Profile.objects.create(user=self.student, teacher=self.teacher, role='student')
        work = Work.objects.create(owner=self.teacher, title='Уравнения')
        position = Position.objects.create(work=work)
        task = Task.objects.create(text_latex='Два плюс два?', answer_mask='{{number: 4}}')
        Candidate.objects.create(position=position, task=task)
        with self.captureOnCommitCallbacks(execute=True):
            run = iw.prepare(work, self.teacher, [self.student.pk])
            iw.issue(run.pk)
        self.attempt = run.attempts.get()
        self.run = run

    def test_start_and_answer_touch_run_file(self):
        before = self.stamp('run', self.run.pk)
        self.assertIsNotNone(before)
        with self.captureOnCommitCallbacks(execute=True):
            iw.start(self.attempt.pk)
        started = self.stamp('run', self.run.pk)
        self.assertNotEqual(started, before, 'начало работы идёт через update() — нужен явный touch')
        point = self.attempt.variant.points.get()
        with self.captureOnCommitCallbacks(execute=True):
            iw.save_answer(self.attempt.pk, point.pk, 0, {'s1': '4'})
        self.assertNotEqual(self.stamp('run', self.run.pk), started)

    def test_progress_fragment_is_stable_while_student_works(self):
        iw.start(self.attempt.pk)
        self.client.force_login(self.teacher)
        url = reverse('independentworks:progress', args=[self.run.pk])
        first = self.client.get(url, {'fragment': 1})
        self.assertEqual(first.status_code, 200)
        self.assertContains(first, 'data-remaining-until="')
        self.assertNotContains(first, '· 0:')
        second = self.client.get(url, {'fragment': 1}, HTTP_IF_NONE_MATCH=first['ETag'] + '-gzip')
        self.assertEqual(second.status_code, 304)
        page = self.client.get(url)
        self.assertContains(page, f'data-live-file="{files.url("run", self.run.pk)}"')

    def test_expiry_flips_state_on_next_full_poll(self):
        iw.start(self.attempt.pk)
        self.attempt.refresh_from_db()
        self.attempt.ends_at = timezone.now() - timedelta(seconds=1)
        self.attempt.save(update_fields=['ends_at'])
        self.client.force_login(self.teacher)
        before = self.stamp('run', self.run.pk)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(reverse('independentworks:progress', args=[self.run.pk]), {'fragment': 1})
        self.assertNotContains(response, 'data-remaining-until="')
        self.assertNotEqual(self.stamp('run', self.run.pk), before, 'завершение по времени тоже меняет файл-версию')
