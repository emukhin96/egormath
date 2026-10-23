"""Заглушка «Вы ушли со страницы»: настройка при выдаче и после неё,
блокировка только при включённой настройке, разовая разблокировка учителем."""
import tempfile
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Profile
from problems.models import Task
from .models import Work, Position, Candidate, Run, Attempt
from . import services as svc


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class LeaveLockTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        User = get_user_model()
        self.teacher = User.objects.create_user('teacher')
        Profile.objects.create(user=self.teacher, role='teacher', base_editor=True)
        self.student = User.objects.create_user('student')
        Profile.objects.create(user=self.student, teacher=self.teacher, role='student')
        self.stranger = User.objects.create_user('stranger')
        Profile.objects.create(user=self.stranger, role='teacher')
        self.work = Work.objects.create(owner=self.teacher, title='Уравнения')
        self.task = Task.objects.create(text_latex='Два плюс два?', answer_mask='{{number: 4}}')
        Candidate.objects.create(position=Position.objects.create(work=self.work), task=self.task)

    def url(self, name, *args):
        return reverse('independentworks:' + name, args=args)

    def begin(self, **kwargs):
        run = svc.prepare(self.work, self.teacher, [self.student.pk], **kwargs)
        svc.issue(run.pk)
        return svc.start(run.attempts.get().pk)

    def leave(self, attempt):
        self.client.force_login(self.student)
        return self.client.post(self.url('lock', attempt.pk), HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()

    def test_issue_form_saves_setting_off_by_default(self):
        self.client.force_login(self.teacher)
        url = reverse('assignment_create') + f'?mode=independent&work={self.work.pk}'
        form = self.client.get(url)
        self.assertContains(form, 'id="id_lock_on_leave"')
        self.assertNotContains(form, 'id="id_lock_on_leave" checked')
        # В обычном задании (листок) заглушки нет
        self.assertNotContains(self.client.get(reverse('assignment_create')), 'id_lock_on_leave')
        self.client.post(url, {'mode': 'independent', 'work': self.work.pk, 'students': [self.student.pk],
                               'duration': 30, 'lock_on_leave': 'on', 'release_mode': 'manual', 'action': 'draft'})
        draft = Run.objects.get()
        self.assertTrue(draft.lock_on_leave)
        resumed = self.client.get(reverse('assignment_create'), {
            'mode': 'independent', 'work': self.work.pk, 'resume': draft.pk})
        self.assertContains(resumed, 'id="id_lock_on_leave" checked')

    def test_locks_only_when_enabled_even_after_issue(self):
        attempt = self.begin()
        self.assertEqual(self.leave(attempt), {'locked': False, 'enabled': False, 'finished': False})
        attempt.refresh_from_db()
        self.assertIsNone(attempt.locked_at)
        # Включили посреди работы — следующий уход уже блокирует
        self.client.force_login(self.teacher)
        self.client.post(self.url('lock_settings', attempt.run_id), {'lock_on_leave': 'on'})
        self.assertEqual(self.leave(attempt), {'locked': True, 'enabled': True, 'finished': False})
        attempt.refresh_from_db()
        locked_at = attempt.locked_at
        self.assertIsNotNone(locked_at)
        self.leave(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.locked_at, locked_at)

    def test_locked_attempt_hides_tasks_and_rejects_answers(self):
        attempt = self.begin(lock_on_leave=True)
        point = attempt.variant.points.get()
        self.leave(attempt)
        page = self.client.get(self.url('attempt', attempt.pk))
        self.assertContains(page, 'aria-describedby="iw-lock-text">')
        self.assertNotContains(page, 'Два плюс два')
        response = self.client.post(self.url('save', attempt.pk, point.pk), {'version': 0, f'p{point.pk}_s1': '4'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()['message'], svc.LOCKED_MESSAGE)
        self.assertEqual(self.client.get(self.url('lock', attempt.pk)).json()['locked'], True)

    def test_teacher_unlocks_once(self):
        attempt = self.begin(lock_on_leave=True)
        self.leave(attempt)
        self.client.force_login(self.teacher)
        progress = self.client.get(self.url('progress', attempt.run_id))
        self.assertContains(progress, 'Задания заблокированы')
        self.assertContains(progress, f'formaction="{self.url("unlock", attempt.pk)}"')
        with patch('independentworks.services.livefiles.touch') as touch:
            response = self.client.post(self.url('unlock', attempt.pk), HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'ok': True})
        touch.assert_any_call('attempt', attempt.pk)
        touch.assert_any_call('run', attempt.run_id)
        attempt.refresh_from_db()
        self.assertIsNone(attempt.locked_at)
        self.client.force_login(self.student)
        page = self.client.get(self.url('attempt', attempt.pk))
        self.assertContains(page, 'aria-describedby="iw-lock-text" hidden>')
        self.assertContains(page, 'Два плюс два')
        point = attempt.variant.points.get()
        self.assertEqual(svc.save_answer(attempt.pk, point.pk, 0, {'s1': '4'}).version, 1)
        # Разблокировка разовая: новый уход снова закрывает задания
        self.assertTrue(self.leave(attempt)['locked'])

    def test_unlock_from_attempt_page_returns_there(self):
        attempt = self.begin(lock_on_leave=True)
        self.leave(attempt)
        self.client.force_login(self.teacher)
        page = self.client.get(self.url('attempt', attempt.pk))
        self.assertContains(page, 'Ученик ушёл со страницы')
        # Учитель задания видит и под заглушкой ученика
        self.assertContains(page, 'Два плюс два')
        response = self.client.post(self.url('unlock', attempt.pk), {'back': 'attempt'})
        self.assertRedirects(response, self.url('attempt', attempt.pk))

    def test_only_owner_teacher_unlocks_and_only_student_locks(self):
        attempt = self.begin(lock_on_leave=True)
        self.leave(attempt)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(self.url('unlock', attempt.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('lock', attempt.pk)).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(self.url('unlock', attempt.pk)).status_code, 403)
        self.assertIsNotNone(Attempt.objects.get(pk=attempt.pk).locked_at)

    def test_turning_setting_off_unlocks_everyone(self):
        attempt = self.begin(lock_on_leave=True)
        self.leave(attempt)
        self.client.force_login(self.teacher)
        self.client.post(self.url('lock_settings', attempt.run_id), {})
        attempt.refresh_from_db()
        self.assertFalse(attempt.run.lock_on_leave)
        self.assertIsNone(attempt.locked_at)

    def test_finished_attempt_is_not_locked(self):
        attempt = self.begin(lock_on_leave=True)
        Attempt.objects.filter(pk=attempt.pk).update(ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.leave(attempt), {'locked': False, 'enabled': True, 'finished': True})

    def test_start_page_warns_about_lock(self):
        run = svc.prepare(self.work, self.teacher, [self.student.pk], lock_on_leave=True)
        svc.issue(run.pk)
        self.client.force_login(self.student)
        page = self.client.get(self.url('attempt', run.attempts.get().pk))
        self.assertContains(page, 'Не уходите со страницы работы')

    def test_progress_fragment_etag_is_stable_with_unlock_button(self):
        """Токен CSRF — в форме вне фрагмента: иначе ETag опроса менялся бы каждый раз."""
        attempt = self.begin(lock_on_leave=True)
        self.leave(attempt)
        self.client.force_login(self.teacher)
        url = self.url('progress', attempt.run_id) + '?fragment=1'
        first = self.client.get(url)
        self.assertContains(first, 'Разблокировать')
        self.assertEqual(self.client.get(url, HTTP_IF_NONE_MATCH=first['ETag']).status_code, 304)
