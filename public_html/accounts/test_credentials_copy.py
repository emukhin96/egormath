"""Логин и пароль ученика — JSON для копирования в буфер (ответ Егора к U1,
07.11): создание ученика и сброс пароля по XHR отвечают данными, без XHR —
прежний редирект с плашкой."""
from django.test import TestCase
from django.urls import reverse

from problems.tests import make_student
from problems.tests import make_teacher

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class CredentialsCopyTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher, 'pupil')
        self.client.login(username='teacher1', password='pass12345')

    def test_reset_returns_credentials_for_xhr(self):
        response = self.client.post(reverse('reset_student_password', args=[self.student.pk]), **XHR)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['username'], 'pupil')
        self.assertTrue(self.client.login(username='pupil', password=data['password']))

    def test_reset_without_xhr_redirects_with_plaque(self):
        response = self.client.post(reverse('reset_student_password', args=[self.student.pk]))
        self.assertRedirects(response, reverse('students'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('students')), 'data-credentials-note')

    def test_create_student_xhr(self):
        response = self.client.post(reverse('students'), {'first_name': 'Иван', 'last_name': 'Петров'}, **XHR)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['username'])
        self.assertTrue(data['password'])

    def test_create_student_invalid_xhr(self):
        response = self.client.post(reverse('students'), {'first_name': '', 'last_name': ''}, **XHR)
        self.assertEqual(response.json(), {'ok': False})

    def test_forms_marked_for_copy(self):
        html = self.client.get(reverse('students')).content.decode()
        self.assertEqual(html.count('data-credentials-copy'), 2)
        self.assertIn('js/credentials_copy.js', html)
