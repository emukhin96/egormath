from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Profile, StudentGroup


class StudentRegistrationTests(TestCase):
    def registration_data(self, **overrides):
        data = {
            'first_name': 'Анна-Мария',
            'last_name': 'О’Коннор',
            'username': 'New.Student-7',
            'password1': 'надёжный пароль 7',
            'password2': 'надёжный пароль 7',
        }
        data.update(overrides)
        return data

    def test_registration_page_is_linked_from_login(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, reverse('register'))

        response = self.client.get(reverse('register'))
        self.assertContains(response, 'Регистрация ученика')
        self.assertContains(response, 'data-registration-form')
        self.assertContains(response, 'js/registration.js')
        self.assertContains(response, 'maxlength="30"')
        self.assertContains(response, 'maxlength="50"', count=2)
        self.assertContains(response, 'maxlength="128"', count=2)
        self.assertNotContains(
            response, 'До 50 символов: буквы, пробел, дефис или апостроф.')

    def test_student_can_register_and_is_logged_in(self):
        response = self.client.post(
            reverse('register'), self.registration_data())

        self.assertRedirects(response, reverse('dashboard'))
        student = User.objects.get(username='new.student-7')
        self.assertEqual(student.first_name, 'Анна-Мария')
        self.assertEqual(student.last_name, 'О’Коннор')
        self.assertTrue(student.check_password('надёжный пароль 7'))
        self.assertEqual(student.profile.role, Profile.ROLE_STUDENT)
        self.assertIsNone(student.profile.teacher)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), student.pk)

    def test_public_pages_use_site_name_and_footer(self):
        for url_name in ('login', 'register'):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertContains(response, 'Математика')
                self.assertContains(response, 'Егор Мухин, 2026')
                self.assertNotContains(response, 'EgorMath')

    def test_pages_include_favicon(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'favicon.svg')
        self.assertContains(response, 'apple-touch-icon.png')
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 301)
        self.assertIn('favicon.ico', response['Location'])

    def test_registered_student_attaches_to_superuser(self):
        admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        self.client.post(reverse('register'), self.registration_data())
        student = User.objects.get(username='new.student-7')
        self.assertEqual(student.profile.teacher, admin)

    def test_superuser_sees_registered_students_in_roster(self):
        admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        self.client.post(reverse('register'), self.registration_data())
        self.client.logout()
        self.client.login(username='admin', password='pass12345')

        response = self.client.get(reverse('students'))
        self.assertContains(response, 'Анна-Мария')
        self.assertContains(response, 'О’Коннор')
        self.assertEqual(
            Profile.students_for(admin).count(), 1)

    def test_superuser_sees_students_without_teacher(self):
        admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        student = User.objects.create_user(
            username='free-student', password='pass12345',
            first_name='Саша', last_name='Саморегистров')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT)
        self.client.login(username='admin', password='pass12345')

        response = self.client.get(reverse('students'))
        self.assertContains(response, 'Саморегистров')
        self.assertEqual(response.context['student_profiles'].count(), 1)

    def test_regular_teacher_does_not_see_unattached_student(self):
        teacher = User.objects.create_user(
            username='teacher1', password='pass12345')
        Profile.objects.create(user=teacher, role=Profile.ROLE_TEACHER)
        self.client.post(reverse('register'), self.registration_data())
        self.client.logout()
        self.client.login(username='teacher1', password='pass12345')

        response = self.client.get(reverse('students'))
        self.assertNotContains(response, 'Анна-Мария')
        self.assertFalse(Profile.students_for(teacher).exists())

    def test_registration_rejects_invalid_and_too_long_values(self):
        invalid_values = (
            ('username', 'ученик'),
            ('username', 'a' * 31),
            ('first_name', 'Анна7'),
            ('last_name', 'И' * 51),
            ('password1', 'p' * 129),
        )
        for field, value in invalid_values:
            with self.subTest(field=field, value=value[:10]):
                data = self.registration_data(**{field: value})
                if field == 'password1':
                    data['password2'] = value
                response = self.client.post(reverse('register'), data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)

        self.assertFalse(User.objects.exists())

    def test_registration_rejects_duplicate_login_ignoring_case(self):
        User.objects.create_user(username='new.student-7', password='secret7')
        response = self.client.post(
            reverse('register'), self.registration_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Этот логин уже занят.')
        self.assertEqual(User.objects.count(), 1)

    def test_registration_rejects_short_or_mismatched_password(self):
        response = self.client.post(
            reverse('register'),
            self.registration_data(password1='12345', password2='12345'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('password1', response.context['form'].errors)

        response = self.client.post(
            reverse('register'),
            self.registration_data(password2='другой пароль'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(User.objects.exists())

    def test_authenticated_user_cannot_open_registration(self):
        student = User.objects.create_user(
            username='student', password='secret7')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT)
        self.client.login(username='student', password='secret7')

        response = self.client.get(reverse('register'))

        self.assertRedirects(response, reverse('dashboard'))


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

    def test_student_dashboard_has_no_ordering_hint(self):
        student = User.objects.create_user(
            username='student1', password='pass12345',
            first_name='Петя', last_name='Ученик')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT)
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Мои задания')
        self.assertNotContains(
            response,
            'Сначала то, что нужно сдать, ниже — работы на проверке и проверенные.')

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

    def test_search_and_ungrouped_filter(self):
        group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        group.students.add(self.student)
        other = User.objects.create_user(
            username='special.login', password='pass12345',
            first_name='Вася', last_name='Другов')
        Profile.objects.create(user=other, role=Profile.ROLE_STUDENT,
                               teacher=self.teacher)

        response = self.client.get(reverse('students'), {'q': 'special'})
        self.assertContains(response, 'Другов')
        self.assertNotContains(response, 'Петя')
        response = self.client.get(
            reverse('students'), {'group': 'ungrouped'})
        self.assertContains(response, 'Другов')
        self.assertNotContains(response, 'Петя')

    def test_bulk_add_remove_and_move_preserves_other_groups(self):
        source = StudentGroup.objects.create(
            teacher=self.teacher, name='Исходная')
        target = StudentGroup.objects.create(
            teacher=self.teacher, name='Целевая')
        extra = StudentGroup.objects.create(
            teacher=self.teacher, name='Олимпиада')
        source.students.add(self.student)
        extra.students.add(self.student)

        url = reverse('students_bulk_groups')
        response = self.client.post(url, {
            'ids': [self.student.pk], 'action': 'move',
            'source_group': source.pk, 'target_group': target.pk,
            'group': source.pk, 'q': 'Петя',
        })
        self.assertEqual(
            response.url,
            f"{reverse('students')}?q=%D0%9F%D0%B5%D1%82%D1%8F&group={source.pk}")
        self.assertNotIn(self.student, source.students.all())
        self.assertIn(self.student, target.students.all())
        self.assertIn(self.student, extra.students.all())

        self.client.post(url, {
            'ids': [self.student.pk], 'action': 'remove',
            'target_group': target.pk,
        })
        self.assertNotIn(self.student, target.students.all())
        self.client.post(url, {
            'ids': [self.student.pk], 'action': 'add',
            'target_group': target.pk,
        })
        self.assertIn(self.student, target.students.all())

    def test_bulk_rejects_foreign_student_and_group(self):
        own = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        other_teacher = User.objects.create_user(
            username='teacher2', password='pass12345')
        Profile.objects.create(user=other_teacher, role=Profile.ROLE_TEACHER)
        foreign_student = User.objects.create_user(
            username='student2', password='pass12345')
        Profile.objects.create(
            user=foreign_student, role=Profile.ROLE_STUDENT,
            teacher=other_teacher)
        foreign_group = StudentGroup.objects.create(
            teacher=other_teacher, name='Чужая')

        self.client.post(reverse('students_bulk_groups'), {
            'ids': [self.student.pk, foreign_student.pk], 'action': 'add',
            'target_group': own.pk,
        })
        self.assertFalse(own.students.exists())
        self.client.post(reverse('students_bulk_groups'), {
            'ids': [self.student.pk], 'action': 'add',
            'target_group': foreign_group.pk,
        })
        self.assertFalse(foreign_group.students.exists())

    def test_superuser_controls_foreign_groups(self):
        other_teacher = User.objects.create_user(
            username='teacher2', password='pass12345',
            first_name='Мария', last_name='Учитель')
        Profile.objects.create(user=other_teacher, role=Profile.ROLE_TEACHER)
        foreign_group = StudentGroup.objects.create(
            teacher=other_teacher, name='Чужая')
        admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'pass12345')
        self.client.login(username='admin', password='pass12345')

        response = self.client.get(reverse('students'))
        self.assertContains(response, 'Чужая')
        response = self.client.get(
            reverse('students'), {'teacher': other_teacher.pk})
        self.assertEqual(list(response.context['groups']), [foreign_group])
        self.client.post(reverse('students_bulk_groups'), {
            'ids': [self.student.pk], 'action': 'add',
            'target_group': foreign_group.pk,
        })
        self.assertIn(self.student, foreign_group.students.all())
        self.client.post(
            reverse('group_rename', args=[foreign_group.pk]),
            {'name': 'Общая'})
        foreign_group.refresh_from_db()
        self.assertEqual(foreign_group.name, 'Общая')
        self.client.post(reverse('group_delete', args=[foreign_group.pk]))
        self.assertFalse(StudentGroup.objects.filter(pk=foreign_group.pk).exists())

        self.client.post(reverse('students'), {
            'create_group': '1', 'name': 'Новая',
            'teacher': other_teacher.pk,
        })
        self.assertTrue(StudentGroup.objects.filter(
            teacher=other_teacher, name='Новая').exists())

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
