from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Profile


class StudentManagementTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher1', password='pass12345',
            first_name='Иван', last_name='Учителев')
        Profile.objects.create(user=self.teacher, role=Profile.ROLE_TEACHER)

    def test_teacher_creates_student(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse('students'), {
            'first_name': 'Пётр', 'last_name': 'Иванов', 'grade': 8,
        })
        # fetch_redirect_response=False: страница-редирект показывает пароль
        # один раз, и лишний GET из assertRedirects «съел» бы его
        self.assertRedirects(response, reverse('students'),
                             fetch_redirect_response=False)
        student = User.objects.get(first_name='Пётр')
        self.assertEqual(student.profile.role, Profile.ROLE_STUDENT)
        self.assertEqual(student.profile.teacher, self.teacher)
        # Учётные данные показываются один раз
        response = self.client.get(reverse('students'))
        self.assertContains(response, student.username)
        self.assertContains(response, 'Пароль')

    def test_reset_password(self):
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('students'), {
            'first_name': 'Пётр', 'last_name': 'Иванов',
        })
        student = User.objects.get(first_name='Пётр')
        old_hash = student.password
        self.client.post(reverse('reset_student_password', args=[student.pk]))
        student.refresh_from_db()
        self.assertNotEqual(student.password, old_hash)

    def test_dashboard_routing(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Кабинет учителя')

    def test_login_required(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
