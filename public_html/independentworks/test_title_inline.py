"""Правка названия самостоятельной на месте (ревизия 03.11, Z4): builder.js
шлёт POST только с полем title, без action; на XHR вид отвечает JSON, по
которому autosave.js показывает тост или откатывает заголовок."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from .models import Work

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class InlineTitleTests(TestCase):
    def setUp(self):
        self.teacher = get_user_model().objects.create_superuser('title_teacher', password='test')
        self.client.force_login(self.teacher)
        self.work = Work.objects.create(owner=self.teacher, title='Старое')
        self.url = reverse('independentworks:edit', args=[self.work.pk])

    def test_xhr_title_only_saves_and_returns_json(self):
        response = self.client.post(self.url, {'title': 'Новое'}, **XHR)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'message': 'Название сохранено'})
        self.work.refresh_from_db()
        self.assertEqual(self.work.title, 'Новое')

    def test_plain_post_title_redirects(self):
        response = self.client.post(self.url, {'title': 'Без JS'})
        self.assertEqual(response.status_code, 302)
        self.work.refresh_from_db()
        self.assertEqual(self.work.title, 'Без JS')

    def test_empty_or_long_title_is_rejected(self):
        for title in ('', 'я' * 191):
            with self.subTest(length=len(title)):
                response = self.client.post(self.url, {'title': title}, **XHR)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()['ok'])
                self.assertIn('190', response.json()['message'])
                self.work.refresh_from_db()
                self.assertEqual(self.work.title, 'Старое')
