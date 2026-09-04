from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Profile, StudentGroup


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


class StudentGroupTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher1', password='pass12345',
            first_name='Иван', last_name='Учителев')
        Profile.objects.create(user=self.teacher, role=Profile.ROLE_TEACHER)
        self.student = User.objects.create_user(
            username='student1', password='pass12345',
            first_name='Петя', last_name='Ученик')
        Profile.objects.create(user=self.student, role=Profile.ROLE_STUDENT,
                               grade=8, teacher=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def test_create_rename_delete_group(self):
        self.client.post(reverse('students'),
                         {'create_group': '', 'name': '8А'})
        group = StudentGroup.objects.get(teacher=self.teacher)
        self.assertEqual(group.name, '8А')

        self.client.post(reverse('group_rename', args=[group.pk]),
                         {'name': '8Б'})
        group.refresh_from_db()
        self.assertEqual(group.name, '8Б')

        self.client.post(reverse('group_delete', args=[group.pk]))
        self.assertFalse(StudentGroup.objects.exists())
        # Ученик не удалился
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())

    def test_student_edit_with_groups(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        response = self.client.post(
            reverse('student_edit', args=[self.student.pk]), {
                'first_name': 'Пётр', 'last_name': 'Ученников',
                'grade': 9, 'groups': [group.pk],
            })
        self.assertRedirects(response, reverse('students'))
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Пётр')
        self.assertEqual(self.student.profile.grade, 9)
        self.assertIn(self.student, group.students.all())
        # Снятие галочки убирает из группы
        self.client.post(
            reverse('student_edit', args=[self.student.pk]), {
                'first_name': 'Пётр', 'last_name': 'Ученников', 'grade': 9,
            })
        self.assertNotIn(self.student, group.students.all())

    def test_filter_by_group(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        other = User.objects.create_user(
            username='student2', password='pass12345',
            first_name='Вася', last_name='Другов')
        Profile.objects.create(user=other, role=Profile.ROLE_STUDENT,
                               teacher=self.teacher)
        group.students.add(self.student)
        response = self.client.get(reverse('students'), {'group': group.pk})
        self.assertContains(response, 'Ученик')
        self.assertNotContains(response, 'Другов')

    def test_foreign_teacher_cannot_touch_group(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        other_teacher = User.objects.create_user(
            username='teacher2', password='pass12345')
        Profile.objects.create(user=other_teacher, role=Profile.ROLE_TEACHER)
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.post(
            reverse('group_delete', args=[group.pk]))
        self.assertEqual(response.status_code, 404)

    def test_assign_worksheet_to_group(self):
        from assignments.models import Assignment
        from worksheets.models import Worksheet
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        group.students.add(self.student)
        worksheet = Worksheet.objects.create(title='Тест', owner=self.teacher)
        self.client.post(
            reverse('assign_worksheet', args=[worksheet.pk]),
            {'groups': [group.pk]})
        self.assertTrue(Assignment.objects.filter(
            worksheet=worksheet, student=self.student).exists())
