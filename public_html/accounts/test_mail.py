"""Почта сайта (PR 5 плана пользователей): команда ``mail_check``,
восстановление пароля по почте, приглашение учителя письмом.

Бэкенд в тестах — ``locmem``, поэтому ``mail_enabled()`` истинно; «почта не
настроена» моделируется ``override_settings(EMAIL_BACKEND=SMTP, EMAIL_HOST='')``,
сбой SMTP — бэкендом ``FailingBackend``.
"""
import re
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.mail.backends.base import BaseEmailBackend
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.mailing import SMTP_BACKEND, mail_enabled

from .models import Profile, TeacherInvite
from .tests import make_admin, make_teacher

NO_MAIL = dict(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST='')


class FailingBackend(BaseEmailBackend):
    """Сервер почты «не принял»: любая отправка — исключение."""

    def send_messages(self, email_messages):
        raise OSError('SMTP недоступен')


class MailEnabledTests(TestCase):
    def test_enabled_by_host_or_non_smtp_backend(self):
        self.assertTrue(mail_enabled())  # locmem в тестах
        with override_settings(**NO_MAIL):
            self.assertFalse(mail_enabled())
        with override_settings(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST='smtp.example.com'):
            self.assertTrue(mail_enabled())


class MailCheckCommandTests(TestCase):
    def test_sends_test_letter_and_reports_backend(self):
        out = StringIO()
        call_command('mail_check', 'to@example.com', stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['to@example.com'])
        self.assertIn('Проверка почты', mail.outbox[0].subject)
        self.assertIn('locmem', out.getvalue())
        self.assertIn('Отправитель:', out.getvalue())
        self.assertIn('отправлено на to@example.com', out.getvalue())

    @override_settings(**NO_MAIL)
    def test_without_host_is_an_error(self):
        out = StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command('mail_check', 'to@example.com', stdout=out)
        self.assertIn('EMAIL_HOST не задан', str(ctx.exception))
        self.assertIn('deploy/MAIL.md', str(ctx.exception))
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST='smtp.example.com',
                       EMAIL_PORT=465, EMAIL_USE_SSL=True, EMAIL_USE_TLS=False,
                       EMAIL_HOST_USER='key-id', EMAIL_HOST_PASSWORD='very-secret')
    def test_smtp_summary_without_password(self):
        out = StringIO()
        with mock.patch('accounts.management.commands.mail_check.mail.send_mail', return_value=1):
            call_command('mail_check', 'to@example.com', stdout=out)
        text = out.getvalue()
        self.assertIn('smtp.example.com:465', text)
        self.assertIn('SSL', text)
        self.assertIn('логин key-id', text)
        self.assertNotIn('very-secret', text)
        with mock.patch('accounts.management.commands.mail_check.mail.send_mail',
                        side_effect=OSError('535 auth failed')):
            with self.assertRaises(CommandError) as ctx:
                call_command('mail_check', 'to@example.com', stdout=StringIO())
        self.assertIn('535 auth failed', str(ctx.exception))


class PasswordResetTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.teacher.email = 'ivan@example.com'
        self.teacher.save()
        self.login_url = reverse('login')
        self.reset_url = reverse('password_reset')
        cache.clear()  # счётчики лимита сброса — в кэше default

    def test_login_links_reset_only_with_mail(self):
        self.assertContains(self.client.get(self.login_url), 'Забыли пароль?')
        self.assertContains(self.client.get(self.login_url), self.reset_url)
        with override_settings(**NO_MAIL):
            response = self.client.get(self.login_url)
            self.assertNotContains(response, 'Забыли пароль?')
            self.assertNotContains(response, self.reset_url)

    @override_settings(**NO_MAIL)
    def test_reset_page_without_mail_explains(self):
        response = self.client.get(self.reset_url)
        self.assertContains(response, 'Восстановление по почте не настроено')
        self.assertNotContains(response, 'name="email"')
        response = self.client.post(self.reset_url, {'email': 'ivan@example.com'})
        self.assertContains(response, 'Восстановление по почте не настроено')
        self.assertEqual(mail.outbox, [])

    def test_full_flow_sets_new_password(self):
        response = self.client.get(self.reset_url)
        self.assertContains(response, 'Восстановление пароля')
        self.assertContains(response, '>Почта</label>')
        response = self.client.post(self.reset_url, {'email': 'Ivan@Example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertContains(self.client.get(reverse('password_reset_done')), 'Письмо отправлено')
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['ivan@example.com'])
        self.assertEqual(message.from_email, 'Математика <no-reply@math.egor.am>')
        self.assertEqual(message.subject, 'Восстановление пароля на сайте «Математика»')
        self.assertIn('для логина teacher1', message.body)
        self.assertIn('Здравствуйте, Иван!', message.body)
        self.assertEqual(message.alternatives, [])  # письмо текстом
        link = re.search(r'http://testserver(/accounts/reset/\S+/)', message.body).group(1)
        response = self.client.get(link)
        self.assertEqual(response.status_code, 302)
        form_url = response['Location']
        self.assertContains(self.client.get(form_url), 'Новый пароль')
        response = self.client.post(form_url, {
            'new_password1': 'новый пароль 9', 'new_password2': 'новый пароль 9'})
        self.assertRedirects(response, reverse('password_reset_complete'))
        self.assertContains(self.client.get(reverse('password_reset_complete')), 'Пароль изменён')
        self.assertTrue(self.client.login(username='teacher1', password='новый пароль 9'))
        # Ссылка одноразовая: после смены пароля токен недействителен
        self.client.logout()
        self.assertContains(self.client.get(link), 'Ссылка недействительна')

    def test_mismatch_and_short_password_are_form_errors(self):
        self.client.post(self.reset_url, {'email': 'ivan@example.com'})
        link = re.search(r'http://testserver(/accounts/reset/\S+/)', mail.outbox[0].body).group(1)
        form_url = self.client.get(link)['Location']
        response = self.client.post(form_url, {'new_password1': 'abc', 'new_password2': 'abd'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'errorlist')
        self.assertFalse(User.objects.get(username='teacher1').check_password('abc'))

    def test_unknown_or_missing_email_shows_same_page_without_mail(self):
        student = User.objects.create_user(username='pupil', password='pass12345')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        for address in ('nobody@example.com', ''):
            response = self.client.post(self.reset_url, {'email': address or 'x@example.com'})
            self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(mail.outbox, [])

    def test_several_accounts_on_one_address_get_a_letter_each(self):
        other = User.objects.create_user(
            username='pupil', password='pass12345', email='ivan@example.com')
        Profile.objects.create(user=other, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        self.client.post(self.reset_url, {'email': 'ivan@example.com'})
        self.assertEqual(len(mail.outbox), 2)
        bodies = '\n'.join(m.body for m in mail.outbox)
        self.assertIn('для логина teacher1', bodies)
        self.assertIn('для логина pupil', bodies)

    def test_rate_limit_per_address(self):
        from .password_reset import RESET_PER_EMAIL
        for _ in range(RESET_PER_EMAIL):
            response = self.client.post(self.reset_url, {'email': 'ivan@example.com'})
            self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), RESET_PER_EMAIL)
        # Сверх лимита — та же страница, но письма нет; регистр и пробелы не обходят лимит
        with self.assertLogs('accounts.password_reset', level='WARNING'):
            response = self.client.post(self.reset_url, {'email': '  IVAN@example.com '})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), RESET_PER_EMAIL)
        # Другой адрес лимитом первого не задет
        other = User.objects.create_user(username='pupil', password='pass12345', email='p@example.com')
        Profile.objects.create(user=other, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        self.client.post(self.reset_url, {'email': 'p@example.com'})
        self.assertEqual(len(mail.outbox), RESET_PER_EMAIL + 1)

    def test_rate_limit_per_ip(self):
        from .password_reset import RESET_PER_IP
        # Чужие и несуществующие адреса тоже считаются: перебор адресов с одного IP
        for i in range(RESET_PER_IP):
            self.client.post(self.reset_url, {'email': f'guess{i}@example.com'},
                             HTTP_X_FORWARDED_FOR='203.0.113.5, 10.0.0.1')
        self.assertEqual(mail.outbox, [])
        response = self.client.post(self.reset_url, {'email': 'ivan@example.com'},
                                    HTTP_X_FORWARDED_FOR='203.0.113.5, 10.0.0.1')
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(mail.outbox, [])
        # С другого IP письмо уходит
        self.client.post(self.reset_url, {'email': 'ivan@example.com'}, HTTP_X_FORWARDED_FOR='203.0.113.6')
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='accounts.test_mail.FailingBackend')
    def test_smtp_failure_keeps_done_page(self):
        with self.assertLogs('django.contrib.auth', level='ERROR'):
            response = self.client.post(self.reset_url, {'email': 'ivan@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))


class InviteMailTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.login(username='admin', password='pass12345')
        self.url = reverse('teachers')
        self.with_email = TeacherInvite.objects.create(
            created_by=self.admin, note='Мария', email='maria@example.com')
        self.without_email = TeacherInvite.objects.create(created_by=self.admin, note='Без почты')
        self.send_url = reverse('invite_send', args=[self.with_email.pk])

    def test_send_button_only_for_invites_with_email_and_mail(self):
        page = self.client.get(self.url)
        self.assertContains(page, self.send_url)
        self.assertContains(page, 'Отправить письмом', count=1)
        self.assertNotContains(page, reverse('invite_send', args=[self.without_email.pk]))
        self.assertContains(page, 'Укажите почту, чтобы отправить ссылку письмом')
        with override_settings(**NO_MAIL):
            page = self.client.get(self.url)
            self.assertNotContains(page, 'Отправить письмом')
            self.assertContains(page, 'Почты нет: скопируйте ссылку и отправьте сами.')
            self.assertContains(page, 'Почты на сайте нет')
            # Ссылка по-прежнему копируется вручную
            self.assertContains(page, f'data-copy="http://testserver{reverse("teacher_join", args=[self.with_email.token])}"')

    def test_new_invite_block_offers_sending(self):
        self.client.post(self.url, {'note': 'Пётр', 'email': 'petr@example.com', 'days': 7})
        invite = TeacherInvite.objects.get(email='petr@example.com')
        page = self.client.get(self.url)
        self.assertContains(page, 'data-new-invite')
        self.assertContains(page, 'отправьте письмом на petr@example.com')
        self.assertContains(page, reverse('invite_send', args=[invite.pk]), count=2)  # блок и список
        self.client.post(self.url, {'note': 'Без почты', 'email': '', 'days': 7})
        page = self.client.get(self.url)
        self.assertContains(page, 'скопируйте и отправьте учителю')
        self.assertNotContains(page, 'отправьте письмом на')

    def test_send_invite_letter(self):
        response = self.client.post(self.send_url, follow=True)
        self.assertRedirects(response, self.url)
        self.assertContains(response, 'Письмо отправлено на maria@example.com')
        self.assertContains(response, 'ws-toast-src')
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['maria@example.com'])
        self.assertEqual(message.from_email, 'Математика <no-reply@math.egor.am>')
        self.assertEqual(message.subject, 'Приглашение на сайт «Математика»')
        self.assertIn('Егор Мухин приглашает вас', message.body)
        self.assertIn('http://testserver' + reverse('teacher_join', args=[self.with_email.token]), message.body)
        until = timezone.localtime(self.with_email.expires_at).strftime('%d.%m.%Y')
        self.assertIn(f'действует до {until}', message.body)
        # Повторная отправка из списка непогашенных — ещё одно письмо
        self.client.post(self.send_url)
        self.assertEqual(len(mail.outbox), 2)

    def test_send_without_email_or_mail_or_rights(self):
        response = self.client.post(reverse('invite_send', args=[self.without_email.pk]), follow=True)
        self.assertContains(response, 'не указана почта')
        with override_settings(**NO_MAIL):
            response = self.client.post(self.send_url, follow=True)
            self.assertContains(response, 'Почта на сайте не настроена')
        self.assertEqual(mail.outbox, [])
        # Погашенное или просроченное — его нет в списке, 404
        self.with_email.expires_at = timezone.now() - timedelta(days=1)
        self.with_email.save()
        self.assertEqual(self.client.post(self.send_url).status_code, 404)
        self.with_email.expires_at = timezone.now() + timedelta(days=1)
        self.with_email.save()
        make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.assertEqual(self.client.post(self.send_url).status_code, 403)
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_BACKEND='accounts.test_mail.FailingBackend')
    def test_smtp_failure_shows_error_not_500(self):
        with self.assertLogs('core.mailing', level='ERROR'):
            response = self.client.post(self.send_url, follow=True)
        self.assertContains(response, 'не отправлено: сервер почты не принял')
        self.assertContains(response, 'msg-error')
