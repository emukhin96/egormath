"""Вход в самостоятельную с другого устройства (Run.lock_device): настройка
при выдаче и после неё, отказ чужому устройству, запрос учителю и
переключение доступа, молчаливый вход при выключенной настройке."""
import tempfile
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Profile
from problems.models import Task
from . import devices
from . import services as svc
from .models import Attempt
from .models import AttemptDevice
from .models import Candidate
from .models import DeviceEvent
from .models import Position
from .models import Run
from .models import Work

PHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
LAPTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class DeviceLabelTests(TestCase):
    def test_labels(self):
        self.assertEqual(devices.device_label(PHONE), 'iPhone, Safari')
        self.assertEqual(devices.device_label(LAPTOP), 'Windows, Chrome')
        self.assertEqual(devices.device_label(
            'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 YaBrowser/25.8 Mobile Safari/537.36'),
            'Android, Яндекс Браузер')
        self.assertEqual(devices.device_label(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:143.0) Gecko/20100101 Firefox/143.0'), 'Mac, Firefox')
        self.assertEqual(devices.device_label(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36 Edg/141.0'),
            'Windows, Edge')
        self.assertEqual(devices.device_label(''), 'Неизвестное устройство')


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class DeviceLockTests(TestCase):
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
        # Два браузера одного ученика и браузер учителя
        self.laptop = Client(HTTP_USER_AGENT=LAPTOP)
        self.phone = Client(HTTP_USER_AGENT=PHONE)
        self.laptop.force_login(self.student)
        self.phone.force_login(self.student)
        self.client.force_login(self.teacher)

    def url(self, name, *args):
        return reverse('independentworks:' + name, args=args)

    def begin(self, **kwargs):
        """Работа начата на ноутбуке: он и становится устройством попытки."""
        run = svc.prepare(self.work, self.teacher, [self.student.pk], **kwargs)
        svc.issue(run.pk)
        attempt = run.attempts.get()
        self.laptop.post(self.url('start', attempt.pk))
        page = self.laptop.get(self.url('attempt', attempt.pk))
        self.assertContains(page, 'Два плюс два?')
        attempt.refresh_from_db()
        return attempt

    def save(self, client, attempt, value='4', version=0):
        point = attempt.variant.points.get()
        return client.post(self.url('save', attempt.pk, point.pk),
                           {'version': version, f'p{point.pk}_number': value}, **AJAX)

    def test_issue_form_saves_setting_off_by_default(self):
        url = reverse('assignment_create') + f'?mode=independent&work={self.work.pk}'
        form = self.client.get(url)
        self.assertContains(form, 'id="id_lock_device"')
        self.assertNotContains(form, 'id="id_lock_device" checked')
        self.assertContains(form, 'Блокировать вход с другого устройства')
        # В обычном задании (листок) настройки нет
        self.assertNotContains(self.client.get(reverse('assignment_create')), 'id_lock_device')
        self.client.post(url, {'mode': 'independent', 'work': self.work.pk, 'students': [self.student.pk],
                               'duration': 30, 'lock_device': 'on', 'release_mode': 'manual', 'action': 'draft'})
        draft = Run.objects.get()
        self.assertTrue(draft.lock_device)
        resumed = self.client.get(reverse('assignment_create'), {
            'mode': 'independent', 'work': self.work.pk, 'resume': draft.pk})
        self.assertContains(resumed, 'id="id_lock_device" checked')

    def test_first_device_is_bound_without_events(self):
        attempt = self.begin(lock_device=True)
        device = AttemptDevice.objects.get()
        self.assertEqual(attempt.device, device)
        self.assertEqual(device.label, 'Windows, Chrome')
        self.assertEqual(str(device.key), self.laptop.cookies[devices.COOKIE].value)
        self.assertTrue(self.laptop.cookies[devices.COOKIE]['httponly'])
        self.assertFalse(DeviceEvent.objects.exists())
        # Повторное открытие с того же устройства ничего не добавляет
        self.laptop.get(self.url('attempt', attempt.pk))
        self.assertEqual(AttemptDevice.objects.count(), 1)
        self.assertNotContains(self.client.get(self.url('progress', attempt.run_id)), 'iw-device-row')

    def test_start_page_warns_when_enabled(self):
        run = svc.prepare(self.work, self.teacher, [self.student.pk], lock_device=True)
        svc.issue(run.pk)
        page = self.laptop.get(self.url('attempt', run.attempts.get().pk))
        self.assertContains(page, 'Выполняйте работу на одном устройстве')
        # До начала работы устройства не различаются
        self.assertFalse(AttemptDevice.objects.exists())

    def test_other_device_is_blocked_and_teacher_sees_request(self):
        attempt = self.begin(lock_device=True)
        page = self.phone.get(self.url('attempt', attempt.pk))
        self.assertContains(page, 'Работа уже открыта на другом устройстве')
        self.assertContains(page, 'Попросите учителя переключить на новое, чтобы увидеть задания здесь.')
        self.assertNotContains(page, 'Два плюс два?')
        self.assertNotContains(page, 'data-iw-focus')
        # Заглушки ухода и журнала активности на чужом устройстве нет
        self.assertNotContains(page, 'data-iw-lock')
        self.assertNotContains(page, 'data-work-activity')
        attempt.refresh_from_db()
        self.assertEqual(attempt.device.label, 'Windows, Chrome')
        request = AttemptDevice.objects.get(label='iPhone, Safari')
        self.assertIsNotNone(request.requested_at)
        self.assertEqual(list(DeviceEvent.objects.values_list('kind', flat=True)), ['denied'])
        # Ответы, сдача, уход и файлы с чужого устройства не принимаются
        self.assertEqual(self.save(self.phone, attempt).status_code, 403)
        self.assertEqual(self.phone.post(self.url('lock', attempt.pk), **AJAX).status_code, 403)
        self.assertEqual(self.phone.post(self.url('submit', attempt.pk), **AJAX).status_code, 403)
        attempt.refresh_from_db()
        self.assertIsNone(attempt.submitted_at)
        self.assertEqual(self.phone.get(self.url('device', attempt.pk)).json(), {'foreign': True, 'finished': False})
        # Первое устройство работает как прежде
        self.assertEqual(self.laptop.get(self.url('device', attempt.pk)).json(), {'foreign': False, 'finished': False})
        self.assertEqual(self.save(self.laptop, attempt).status_code, 200)
        # Учитель видит запрос в таблице (и во фрагменте опроса) и в работе ученика
        for url in (self.url('progress', attempt.run_id), self.url('progress', attempt.run_id) + '?fragment=1'):
            table = self.client.get(url)
            self.assertContains(table, 'Вход с другого устройства')
            self.assertContains(table, 'iPhone, Safari')
            self.assertContains(table, self.url('switch_device', attempt.pk, request.pk))
        timeline = self.client.get(self.url('attempt', attempt.pk))
        self.assertContains(timeline, 'Пытается войти с другого устройства: iPhone, Safari')
        self.assertContains(timeline, 'Сейчас работа открыта на: Windows, Chrome')
        self.assertContains(timeline, 'Пытался войти с другого устройства')

    def test_reloads_are_one_try(self):
        attempt = self.begin(lock_device=True)
        for _ in range(3):
            self.phone.get(self.url('attempt', attempt.pk))
        self.assertEqual(DeviceEvent.objects.count(), 1)
        # Опрос заглушки попыткой не считается
        self.phone.get(self.url('device', attempt.pk))
        self.assertEqual(DeviceEvent.objects.count(), 1)
        DeviceEvent.objects.update(at=timezone.now() - timedelta(minutes=2))
        self.phone.get(self.url('attempt', attempt.pk))
        self.assertEqual(DeviceEvent.objects.count(), 2)

    def test_teacher_switches_access(self):
        attempt = self.begin(lock_device=True)
        self.phone.get(self.url('attempt', attempt.pk))
        phone = AttemptDevice.objects.get(label='iPhone, Safari')
        # Сам ученик доступ не переключит
        self.assertEqual(self.phone.post(self.url('switch_device', attempt.pk, phone.pk)).status_code, 403)
        attempt.refresh_from_db()
        self.assertEqual(attempt.device.label, 'Windows, Chrome')
        response = self.client.post(self.url('switch_device', attempt.pk, phone.pk))
        self.assertRedirects(response, self.url('progress', attempt.run_id))
        attempt.refresh_from_db()
        phone.refresh_from_db()
        self.assertEqual(attempt.device, phone)
        self.assertIsNone(phone.requested_at)
        self.assertEqual(list(DeviceEvent.objects.values_list('kind', flat=True)), ['denied', 'switch'])
        # Телефон работает, ноутбук закрыт: страница открытой работы узнаёт
        # об этом опросом и ответы оттуда не принимаются
        self.assertContains(self.phone.get(self.url('attempt', attempt.pk)), 'Два плюс два?')
        self.assertEqual(self.save(self.phone, attempt).status_code, 200)
        self.assertEqual(self.laptop.get(self.url('device', attempt.pk)).json()['foreign'], True)
        self.assertEqual(self.save(self.laptop, attempt, version=1).status_code, 403)
        # Опрос сам по себе запроса не создаёт; запрос — заново открытая страница
        table = self.client.get(self.url('progress', attempt.run_id))
        self.assertNotContains(table, 'iw-device-row')
        self.assertContains(table, 'доступ переключён: iPhone, Safari')
        self.assertContains(self.laptop.get(self.url('attempt', attempt.pk)), 'Работа уже открыта на другом устройстве')
        self.assertContains(self.client.get(self.url('progress', attempt.run_id)), 'Windows, Chrome')
        self.assertContains(self.client.get(self.url('attempt', attempt.pk)), 'Учитель переключил доступ')

    def test_teacher_dismisses_request(self):
        attempt = self.begin(lock_device=True)
        self.phone.get(self.url('attempt', attempt.pk))
        phone = AttemptDevice.objects.get(label='iPhone, Safari')
        self.client.post(self.url('dismiss_device', attempt.pk, phone.pk))
        phone.refresh_from_db()
        self.assertIsNone(phone.requested_at)
        table = self.client.get(self.url('progress', attempt.run_id))
        self.assertNotContains(table, 'iw-device-row')
        self.assertContains(table, 'пытался войти с другого устройства: iPhone, Safari')
        # Телефон по-прежнему не пущен
        self.assertEqual(self.save(self.phone, attempt).status_code, 403)

    def test_setting_off_lets_in_silently_and_reports(self):
        attempt = self.begin()
        page = self.phone.get(self.url('attempt', attempt.pk))
        self.assertContains(page, 'Два плюс два?')
        self.assertNotContains(page, 'Попросите учителя переключить на новое, чтобы увидеть задания здесь.')
        attempt.refresh_from_db()
        self.assertEqual(attempt.device.label, 'iPhone, Safari')
        self.assertEqual(list(DeviceEvent.objects.values_list('kind', flat=True)), ['enter'])
        # Оба устройства работают
        self.assertEqual(self.save(self.phone, attempt).status_code, 200)
        self.assertEqual(self.save(self.laptop, attempt, value='5', version=1).status_code, 200)
        table = self.client.get(self.url('progress', attempt.run_id) + '?fragment=1')
        self.assertContains(table, 'вошёл с другого устройства: iPhone, Safari')
        self.assertNotContains(table, 'iw-device-row')
        self.assertNotContains(table, '×2')
        # Вернулся на ноутбук и снова на телефон — счёт входов, не всех событий
        self.laptop.get(self.url('attempt', attempt.pk))
        self.phone.get(self.url('attempt', attempt.pk))
        self.assertContains(self.client.get(self.url('progress', attempt.run_id)), ' ×3</div>')
        timeline = self.client.get(self.url('attempt', attempt.pk))
        self.assertContains(timeline, 'Вошёл с другого устройства')
        self.assertNotContains(timeline, 'iw-device-note')

    def test_setting_can_be_changed_during_work(self):
        attempt = self.begin()
        self.phone.get(self.url('attempt', attempt.pk))
        # Включили посреди работы: остаётся последнее вошедшее устройство
        self.client.post(self.url('device_settings', attempt.run_id), {'lock_device': 'on'})
        self.assertTrue(Run.objects.get().lock_device)
        self.assertEqual(self.save(self.phone, attempt).status_code, 200)
        self.assertEqual(self.save(self.laptop, attempt, version=1).status_code, 403)
        self.laptop.get(self.url('attempt', attempt.pk))
        self.assertContains(self.client.get(self.url('progress', attempt.run_id)), 'iw-device-row')
        # Выключили: запросы снимаются, ждавшее устройство входит само
        self.client.post(self.url('device_settings', attempt.run_id), {})
        self.assertFalse(AttemptDevice.objects.filter(requested_at__isnull=False).exists())
        self.assertEqual(self.laptop.get(self.url('device', attempt.pk)).json()['foreign'], False)
        self.assertContains(self.laptop.get(self.url('attempt', attempt.pk)), 'Два плюс два?')

    def test_lost_cookie_is_another_device(self):
        attempt = self.begin(lock_device=True)
        del self.laptop.cookies[devices.COOKIE]
        self.assertEqual(self.save(self.laptop, attempt).status_code, 403)
        self.assertContains(self.laptop.get(self.url('attempt', attempt.pk)), 'Работа уже открыта на другом устройстве')
        self.assertEqual(AttemptDevice.objects.count(), 2)

    def test_finished_work_is_open_from_any_device(self):
        attempt = self.begin(lock_device=True)
        self.laptop.post(self.url('submit', attempt.pk))
        page = self.phone.get(self.url('attempt', attempt.pk))
        self.assertNotContains(page, 'Работа уже открыта на другом устройстве')
        self.assertEqual(AttemptDevice.objects.count(), 1)
        self.assertFalse(DeviceEvent.objects.exists())

    def test_activity_journal_ignores_foreign_device(self):
        attempt = self.begin(lock_device=True)
        self.phone.get(self.url('attempt', attempt.pk))
        url = reverse('workaudit:events', args=['attempt', attempt.pk])
        self.assertEqual(self.phone.post(url, '{"events": []}', content_type='application/json').status_code, 409)
        # С текущего устройства пакет доходит до разбора (пустой — 400)
        self.assertEqual(self.laptop.post(url, '{"events": []}', content_type='application/json').status_code, 400)

    def test_only_owner_teacher_manages_devices(self):
        attempt = self.begin(lock_device=True)
        self.phone.get(self.url('attempt', attempt.pk))
        phone = AttemptDevice.objects.get(label='iPhone, Safari')
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(self.url('switch_device', attempt.pk, phone.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('dismiss_device', attempt.pk, phone.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('device_settings', attempt.run_id), {}).status_code, 404)
        attempt.refresh_from_db()
        self.assertEqual(attempt.device.label, 'Windows, Chrome')
        self.assertTrue(Run.objects.get().lock_device)
        # Устройство другой попытки не подставить
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.url('switch_device', attempt.pk, phone.pk + 100)).status_code, 404)
        self.assertEqual(Attempt.objects.get().device.label, 'Windows, Chrome')

    def test_attempt_with_devices_can_be_deleted(self):
        # Attempt.device и AttemptDevice.attempt ссылаются друг на друга
        attempt = self.begin(lock_device=True)
        self.phone.get(self.url('attempt', attempt.pk))
        attempt.delete()
        self.assertFalse(AttemptDevice.objects.exists())
        self.assertFalse(DeviceEvent.objects.exists())
