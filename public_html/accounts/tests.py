from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Profile, StudentGroup, TeacherInvite


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

    def test_pages_include_production_favicon(self):
        # Django гоняет тесты с DEBUG=False, как на проде.
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'href="/static/favicon.svg"')
        self.assertContains(response, 'apple-touch-icon.png')
        self.assertNotContains(response, 'favicon-local')
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/static/favicon.ico')

    def test_pages_include_local_favicon(self):
        with self.settings(DEBUG=True):
            response = self.client.get(reverse('login'))
            self.assertContains(response, 'favicon-local.svg')
            self.assertContains(response, 'apple-touch-icon-local.png')
            response = self.client.get('/favicon.ico')
            self.assertEqual(response.status_code, 302)
            self.assertIn('favicon-local.ico', response['Location'])

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
        page = self.client.get(reverse('students'))
        self.assertContains(page, f'data-dialog-open="reset-password-{student.pk}"')
        self.assertContains(page, 'Сбросить и показать новый пароль')
        response = self.client.post(reverse('reset_student_password', args=[student.pk]))
        self.assertRedirects(response, reverse('students'), fetch_redirect_response=False)
        student.refresh_from_db()
        self.assertNotEqual(student.password, old_hash)
        page = self.client.get(reverse('students'))
        credentials = page.context['new_credentials']
        self.assertEqual(credentials['username'], student.username)
        self.assertTrue(student.check_password(credentials['password']))
        self.assertIsNone(self.client.get(reverse('students')).context['new_credentials'])

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

    def test_list_is_split_by_groups(self):
        # Без фильтра — блоки по группам; ученик из двух групп в обеих,
        # в строке — только другая его группа; без группы — последним блоком.
        group_a = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        group_b = StudentGroup.objects.create(teacher=self.teacher, name='8Б')
        other = User.objects.create_user(
            username='student2', password='pass12345',
            first_name='Вася', last_name='Другов')
        Profile.objects.create(user=other, role=Profile.ROLE_STUDENT,
                               teacher=self.teacher)
        lonely = User.objects.create_user(
            username='student3', password='pass12345',
            first_name='Оля', last_name='Одинокова')
        Profile.objects.create(user=lonely, role=Profile.ROLE_STUDENT,
                               teacher=self.teacher)
        group_a.students.add(self.student, other)
        group_b.students.add(self.student)
        response = self.client.get(reverse('students'))
        sections = response.context['student_sections']
        self.assertEqual(
            [(s['group'], [p.user for p, _ in s['rows']]) for s in sections],
            [(group_a, [other, self.student]), (group_b, [self.student]),
             (None, [lonely])])
        self.assertEqual(dict((p.user, groups) for p, groups in sections[0]['rows']),
                         {other: [], self.student: [group_b]})
        self.assertContains(response, 'class="student-group-head"', 3)
        self.assertContains(response, 'Без группы</span>')
        # Счётчик и диалоги сброса пароля — по разным ученикам, без повторов.
        self.assertContains(response, 'id="reset-password-%d"' % self.student.pk, 1)

    def test_list_without_groups_is_flat(self):
        response = self.client.get(reverse('students'))
        self.assertIsNone(response.context['student_sections'])
        self.assertNotContains(response, 'student-group-head')
        self.assertContains(response, 'Ученик')

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

    def test_superuser_teacher_filter_splits_by_that_teacher_groups_only(self):
        # Ученик учителя X состоит в группе учителя Y: при ?teacher=X блока
        # группы Y нет, ученик — «без группы», как и в фильтре group=ungrouped.
        other_teacher = User.objects.create_user(
            username='teacher2', password='pass12345',
            first_name='Мария', last_name='Учитель')
        Profile.objects.create(user=other_teacher, role=Profile.ROLE_TEACHER)
        own_group = StudentGroup.objects.create(teacher=self.teacher, name='8А')
        foreign_group = StudentGroup.objects.create(teacher=other_teacher, name='Чужая')
        foreign_group.students.add(self.student)
        classmate = User.objects.create_user(
            username='student2', password='pass12345',
            first_name='Вася', last_name='Другов')
        Profile.objects.create(user=classmate, role=Profile.ROLE_STUDENT,
                               teacher=self.teacher)
        own_group.students.add(classmate)
        User.objects.create_superuser('admin', 'admin@example.com', 'pass12345')
        self.client.login(username='admin', password='pass12345')
        response = self.client.get(reverse('students'), {'teacher': self.teacher.pk})
        sections = response.context['student_sections']
        self.assertEqual(
            [(s['group'], [p.user for p, _ in s['rows']]) for s in sections],
            [(own_group, [classmate]), (None, [self.student])])
        # Чужая группа видна только как «другие группы» в строке, не блоком
        self.assertNotContains(response, '?group=%d&amp;teacher=' % foreign_group.pk)
        ungrouped = self.client.get(
            reverse('students'), {'teacher': self.teacher.pk, 'group': 'ungrouped'})
        self.assertEqual([p.user for p in ungrouped.context['student_profiles']],
                         [self.student])
        # Без фильтра по учителю чужая группа — обычный блок
        response = self.client.get(reverse('students'))
        self.assertIn(foreign_group, [s['group'] for s in response.context['student_sections']])

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


class LogoutCsrfTests(TestCase):
    def test_logout_requires_current_csrf_token(self):
        """Устаревший токен отклоняется, актуальный позволяет выйти."""
        from django.middleware.csrf import get_token, rotate_token
        from django.test import Client, RequestFactory

        user = User.objects.create_user(username='logout-test')
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        request = RequestFactory().get('/')
        stale_token = get_token(request)
        rotate_token(request)
        client.cookies['csrftoken'] = request.META['CSRF_COOKIE']
        response = client.post(reverse('logout'), {'csrfmiddlewaretoken': stale_token})
        self.assertEqual(response.status_code, 403)
        self.assertIn('_auth_user_id', client.session)
        response = client.post(reverse('logout'), {
            'csrfmiddlewaretoken': request.META['CSRF_COOKIE'],
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', client.session)

    def test_logout_refreshes_token_at_submit_without_sidebar(self):
        """Старая вкладка использует свежую cookie, даже без боковой панели."""
        import shutil
        import subprocess
        from pathlib import Path

        node = shutil.which('node')
        if not node:
            self.skipTest('node не установлен')
        script = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const field = {value: 'old-rendered-token'};
let submit;
const form = {
  addEventListener: (name, handler) => { if (name === 'submit') submit = handler; },
  querySelector: () => field,
};
const document = {
  cookie: 'csrftoken=initial-token',
  querySelector: () => form,
  querySelectorAll: () => [],
  getElementById: () => null,
  addEventListener: (name, handler) => { if (name === 'DOMContentLoaded') handler(); },
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {document});
// Cookie поменялась после загрузки страницы, как при входе в другой вкладке.
document.cookie = 'sessionid=session; csrftoken=current-token';
submit();
assert.equal(field.value, 'current-token');
// Без доступной cookie сохраняем серверный токен формы.
document.cookie = '';
submit();
assert.equal(field.value, 'current-token');
'''
        js = Path(__file__).resolve().parents[1] / 'static/js/shell.js'
        subprocess.check_call([node, '-e', script, str(js)])


def make_admin():
    return User.objects.create_superuser(
        'admin', 'admin@example.com', 'pass12345',
        first_name='Егор', last_name='Мухин')


def make_teacher(username='teacher1', **profile_fields):
    user = User.objects.create_user(
        username=username, password='pass12345',
        first_name='Иван', last_name='Учителев')
    Profile.objects.create(user=user, role=Profile.ROLE_TEACHER, **profile_fields)
    return user


class TeacherInviteTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.invite = TeacherInvite.objects.create(
            created_by=self.admin, note='Мария Петрова')
        self.url = reverse('teacher_join', args=[self.invite.token])

    def join_data(self, **overrides):
        data = {
            'first_name': 'Мария',
            'last_name': 'Петрова',
            'username': 'petrova',
            'password1': 'надёжный пароль 7',
            'password2': 'надёжный пароль 7',
            'email': '',
        }
        data.update(overrides)
        return data

    def test_valid_token_shows_form(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Регистрация учителя')
        self.assertContains(response, 'Вас пригласил Егор Мухин')
        self.assertContains(response, 'data-registration-form')
        self.assertContains(response, 'data-suggest-username')
        self.assertContains(response, 'name="email"')

    def test_expired_token_shows_explanation_without_form(self):
        self.invite.expires_at = timezone.now() - timedelta(minutes=1)
        self.invite.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Срок действия приглашения истёк')
        self.assertNotContains(response, 'data-registration-form')
        response = self.client.post(self.url, self.join_data())
        self.assertContains(response, 'Срок действия приглашения истёк')
        self.assertFalse(User.objects.filter(username='petrova').exists())

    def test_used_token_shows_explanation(self):
        self.invite.used_at = timezone.now()
        self.invite.save()
        response = self.client.get(self.url)
        self.assertContains(response, 'уже зарегистрирован учитель')
        self.assertNotContains(response, 'data-registration-form')

    def test_revoked_or_unknown_token_shows_explanation(self):
        self.invite.delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Приглашение отозвано')
        self.assertNotContains(response, 'data-registration-form')
        response = self.client.get(reverse('teacher_join', args=['nope']))
        self.assertContains(response, 'Ссылка недействительна')

    def test_registration_creates_teacher_and_logs_in(self):
        response = self.client.post(
            self.url, self.join_data(email='maria@example.com'))
        self.assertRedirects(response, reverse('dashboard'))
        teacher = User.objects.get(username='petrova')
        self.assertEqual(teacher.first_name, 'Мария')
        self.assertEqual(teacher.email, 'maria@example.com')
        self.assertTrue(teacher.check_password('надёжный пароль 7'))
        self.assertEqual(teacher.profile.role, Profile.ROLE_TEACHER)
        self.assertFalse(teacher.profile.base_editor)
        self.assertEqual(teacher.profile.invited_by, self.admin)
        self.assertEqual(len(teacher.profile.student_code), 8)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), teacher.pk)
        self.invite.refresh_from_db()
        self.assertIsNotNone(self.invite.used_at)
        self.assertEqual(self.invite.used_by, teacher)
        # Кабинет учителя без импорта задачников — приглашённый не редактор
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Кабинет учителя')
        self.assertNotContains(response, 'Импорт задачников')
        self.assertNotContains(response, reverse('teachers'))

    def test_invite_grants_base_editor(self):
        self.invite.base_editor = True
        self.invite.save()
        self.client.post(self.url, self.join_data())
        teacher = User.objects.get(username='petrova')
        self.assertTrue(teacher.profile.base_editor)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Импорт задачников')

    def test_empty_username_is_generated_from_name(self):
        response = self.client.post(
            self.url, self.join_data(username=''), follow=True)
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(User.objects.filter(username='petrova.mariya').exists())
        self.assertContains(response, 'Ваш логин: petrova.mariya')

    def test_generated_username_gets_suffix_when_taken(self):
        # JS подсказывает логин только placeholder'ом, поле уходит пустым —
        # тёзка уже зарегистрированного получает номер, а не ошибку
        User.objects.create_user(username='petrova.mariya', password='x')
        response = self.client.post(
            self.url, self.join_data(username=''), follow=True)
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(User.objects.filter(username='petrova.mariya2').exists())
        self.assertContains(response, 'Ваш логин: petrova.mariya2')

    def test_invite_email_prefills_form(self):
        self.invite.email = 'maria@example.com'
        self.invite.save()
        response = self.client.get(self.url)
        self.assertContains(response, 'value="maria@example.com"')

    def test_duplicate_username_is_form_error(self):
        User.objects.create_user(username='petrova', password='x')
        response = self.client.post(self.url, self.join_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Этот логин уже занят.')
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.used_at)

    def test_token_cannot_be_used_twice(self):
        self.client.post(self.url, self.join_data())
        self.client.logout()
        response = self.client.post(
            self.url, self.join_data(username='petrova2'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'уже зарегистрирован учитель')
        self.assertFalse(User.objects.filter(username='petrova2').exists())
        self.assertEqual(
            Profile.objects.filter(role=Profile.ROLE_TEACHER).count(), 1)

    def test_claim_is_atomic(self):
        # Условный UPDATE: второй «одновременный» запрос с тем же токеном
        # приглашение не получает, даже если его объект ещё не знает о погашении
        stale = TeacherInvite.objects.get(pk=self.invite.pk)
        self.assertTrue(self.invite.claim())
        self.assertFalse(stale.claim())
        self.assertFalse(TeacherInvite.pending().exists())

    def test_logged_in_user_is_redirected(self):
        self.client.login(username='admin', password='pass12345')
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('dashboard'))
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.used_at)


class StudentRegistrationLinkTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.teacher = make_teacher()
        self.code = self.teacher.profile.student_code

    def registration_data(self, **overrides):
        data = {
            'first_name': 'Анна',
            'last_name': 'Иванова',
            'username': 'ivanova',
            'password1': 'надёжный пароль 7',
            'password2': 'надёжный пароль 7',
        }
        data.update(overrides)
        return data

    def test_teacher_profile_gets_student_code(self):
        self.assertEqual(len(self.code), 8)
        student = User.objects.create_user(username='s1')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT)
        self.assertIsNone(student.profile.student_code)

    def test_link_attaches_student_to_teacher(self):
        response = self.client.get(reverse('register'), {'t': self.code})
        self.assertContains(response, 'Ваш учитель — Иван Учителев.')
        self.assertContains(
            response, f'name="teacher_code" value="{self.code}"')
        response = self.client.post(
            reverse('register'),
            self.registration_data(teacher_code=self.code))
        self.assertRedirects(response, reverse('dashboard'))
        student = User.objects.get(username='ivanova')
        self.assertEqual(student.profile.teacher, self.teacher)
        self.assertEqual(Profile.students_for(self.teacher).count(), 1)

    def test_without_code_goes_to_default_teacher(self):
        response = self.client.post(
            reverse('register'), self.registration_data())
        self.assertRedirects(response, reverse('dashboard'))
        student = User.objects.get(username='ivanova')
        self.assertEqual(student.profile.teacher, self.admin)

    def test_invalid_code_is_form_error(self):
        response = self.client.get(reverse('register'), {'t': 'badcode1'})
        self.assertContains(response, 'Ссылка недействительна')
        self.assertContains(response, 'name="teacher_code" value="badcode1"')
        response = self.client.post(
            reverse('register'), self.registration_data(teacher_code='badcode1'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ссылка недействительна')
        self.assertFalse(User.objects.filter(username='ivanova').exists())

    def test_disabled_teacher_code_is_rejected(self):
        self.teacher.is_active = False
        self.teacher.save()
        response = self.client.post(
            reverse('register'), self.registration_data(teacher_code=self.code))
        self.assertContains(response, 'Ссылка недействительна')
        self.assertFalse(User.objects.filter(username='ivanova').exists())

    def test_students_page_shows_registration_link(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('students'))
        link = f"{reverse('register')}?t={self.code}"
        self.assertContains(response, 'Ссылка для самостоятельной регистрации')
        self.assertContains(response, f'data-copy="http://testserver{link}"')

    def test_superuser_without_profile_gets_code_on_students_page(self):
        self.assertFalse(Profile.objects.filter(user=self.admin).exists())
        self.client.login(username='admin', password='pass12345')
        response = self.client.get(reverse('students'))
        profile = Profile.objects.get(user=self.admin)
        self.assertEqual(profile.role, Profile.ROLE_TEACHER)
        self.assertContains(response, f'?t={profile.student_code}')
        # Ученик по ссылке суперпользователя — к нему же
        self.client.logout()
        self.client.post(
            reverse('register'),
            self.registration_data(teacher_code=profile.student_code))
        self.assertEqual(
            User.objects.get(username='ivanova').profile.teacher, self.admin)


class TeachersPageTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.teacher = make_teacher()
        student = User.objects.create_user(
            username='student1', password='pass12345',
            first_name='Петя', last_name='Ученик')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT,
                               teacher=self.teacher)
        from worksheets.models import Worksheet
        Worksheet.objects.create(title='Листок', owner=self.teacher)
        self.url = reverse('teachers')

    def test_only_superuser_opens_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
        self.client.login(username='teacher1', password='pass12345')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        # is_staff недостаточно
        self.teacher.is_staff = True
        self.teacher.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.login(username='student1', password='pass12345')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        for name, args in (('teacher_reset_password', [self.teacher.pk]),
                           ('teacher_toggle_active', [self.teacher.pk]),
                           ('teacher_toggle_base_editor', [self.teacher.pk]),
                           ('invite_revoke', [1])):
            with self.subTest(name=name):
                response = self.client.post(reverse(name, args=args))
                self.assertEqual(response.status_code, 403)

    def test_superuser_sees_table_and_menu_item(self):
        self.client.login(username='admin', password='pass12345')
        response = self.client.get(self.url)
        self.assertContains(response, 'Иван Учителев')
        self.assertContains(response, 'teacher1')
        self.assertContains(response, 'Егор Мухин')
        rows = {user.username: user for user in response.context['teacher_list']}
        self.assertEqual(rows['teacher1'].students_count, 1)
        self.assertEqual(rows['teacher1'].worksheets_count, 1)
        self.assertEqual(rows['admin'].students_count, 0)
        self.assertContains(response, 'data-dialog-open="reset-password-%d"' % self.teacher.pk)
        # Пункт «Учителя» в меню — только суперпользователю
        self.assertContains(response, f'href="{self.url}"')
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, f'href="{self.url}"')

    def test_reset_password_shows_credentials_once(self):
        self.client.login(username='admin', password='pass12345')
        old_hash = self.teacher.password
        response = self.client.post(
            reverse('teacher_reset_password', args=[self.teacher.pk]))
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.teacher.refresh_from_db()
        self.assertNotEqual(self.teacher.password, old_hash)
        page = self.client.get(self.url)
        credentials = page.context['new_credentials']
        self.assertEqual(credentials['username'], 'teacher1')
        self.assertTrue(self.teacher.check_password(credentials['password']))
        self.assertContains(page, credentials['password'])
        self.assertIsNone(self.client.get(self.url).context['new_credentials'])

    def test_cannot_reset_own_password(self):
        # set_password без update_session_auth_hash разлогинил бы
        # администратора, а новый пароль показать было бы уже некому
        self.client.login(username='admin', password='pass12345')
        page = self.client.get(self.url)
        self.assertNotContains(
            page, 'data-dialog-open="reset-password-%d"' % self.admin.pk)
        self.assertNotContains(page, 'id="reset-password-%d"' % self.admin.pk)
        self.assertContains(page, f'href="{reverse("profile")}"')
        old_hash = self.admin.password
        response = self.client.post(
            reverse('teacher_reset_password', args=[self.admin.pk]))
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.password, old_hash)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.admin.pk)
        self.assertIsNone(page.context['new_credentials'])

    def test_toggle_active_but_not_self(self):
        self.client.login(username='admin', password='pass12345')
        self.client.post(reverse('teacher_toggle_active', args=[self.teacher.pk]))
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        self.assertFalse(
            self.client.login(username='teacher1', password='pass12345'))
        self.client.login(username='admin', password='pass12345')
        page = self.client.get(self.url)
        self.assertContains(page, 'отключён')
        self.assertContains(page, 'Включить')
        self.client.post(reverse('teacher_toggle_active', args=[self.teacher.pk]))
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.is_active)
        response = self.client.post(
            reverse('teacher_toggle_active', args=[self.admin.pk]))
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_toggle_base_editor(self):
        self.client.login(username='admin', password='pass12345')
        url = reverse('teacher_toggle_base_editor', args=[self.teacher.pk])
        self.client.post(url, {'base_editor': '1'})
        self.teacher.profile.refresh_from_db()
        self.assertTrue(self.teacher.profile.base_editor)
        # Повторная отправка того же значения ничего не переключает
        self.client.post(url, {'base_editor': '1'})
        self.teacher.profile.refresh_from_db()
        self.assertTrue(self.teacher.profile.base_editor)
        self.client.post(url)
        self.teacher.profile.refresh_from_db()
        self.assertFalse(self.teacher.profile.base_editor)
        # У суперпользователя право подразумевается — переключателя нет
        response = self.client.post(
            reverse('teacher_toggle_base_editor', args=[self.admin.pk]),
            {'base_editor': '1'})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(Profile.objects.filter(user=self.admin, base_editor=True).exists())

    def test_create_invite_shows_link_once(self):
        self.client.login(username='admin', password='pass12345')
        response = self.client.post(self.url, {
            'note': 'Мария', 'email': '', 'days': 7, 'base_editor': '1',
        })
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        invite = TeacherInvite.objects.get()
        self.assertEqual(invite.created_by, self.admin)
        self.assertEqual(invite.note, 'Мария')
        self.assertTrue(invite.base_editor)
        self.assertAlmostEqual(
            invite.expires_at, timezone.now() + timedelta(days=7),
            delta=timedelta(minutes=1))
        link = reverse('teacher_join', args=[invite.token])
        page = self.client.get(self.url)
        self.assertContains(page, 'data-new-invite')
        self.assertContains(page, f'<code>http://testserver{link}</code>')
        self.assertContains(page, 'Непогашенные приглашения')
        self.assertContains(page, 'Мария')
        # Разовый блок пропал, но «Скопировать» в списке непогашенных остаётся (R03-1)
        page = self.client.get(self.url)
        self.assertNotContains(page, 'data-new-invite')
        self.assertNotContains(page, f'<code>http://testserver{link}</code>')
        self.assertContains(page, f'data-copy="http://testserver{link}" title="Скопировать ссылку-приглашение">Скопировать<')
        self.assertContains(page, 'Можно ред. базу')
        self.assertNotContains(page, 'Правит базу')
        # Ссылка действительно ведёт на регистрацию
        self.client.logout()
        self.assertContains(self.client.get(link), 'Регистрация учителя')

    def test_revoke_invite(self):
        self.client.login(username='admin', password='pass12345')
        invite = TeacherInvite.objects.create(created_by=self.admin, note='Мария')
        link = reverse('teacher_join', args=[invite.token])
        response = self.client.post(reverse('invite_revoke', args=[invite.pk]))
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(TeacherInvite.objects.exists())
        self.client.logout()
        self.assertContains(self.client.get(link), 'Приглашение отозвано')

    def test_pending_list_hides_used_and_expired(self):
        self.client.login(username='admin', password='pass12345')
        TeacherInvite.objects.create(created_by=self.admin, note='Живое')
        TeacherInvite.objects.create(
            created_by=self.admin, note='Погашенное',
            used_at=timezone.now(), used_by=self.teacher)
        TeacherInvite.objects.create(
            created_by=self.admin, note='Просроченное',
            expires_at=timezone.now() - timedelta(days=1))
        page = self.client.get(self.url)
        self.assertEqual([i.note for i in page.context['invites']], ['Живое'])
        # Погашенное отозвать нельзя — его уже нет в списке
        used = TeacherInvite.objects.get(note='Погашенное')
        response = self.client.post(reverse('invite_revoke', args=[used.pk]))
        self.assertEqual(response.status_code, 404)


class TeacherProfileTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.url = reverse('profile')

    def test_header_links_name_to_profile_for_teacher_only(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, f'class="user-name" href="{self.url}"')
        student = User.objects.create_user(
            username='student1', password='pass12345')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT)
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, self.url)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_update_name_and_email(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'value="Учителев"')
        response = self.client.post(self.url, {
            'first_name': 'Мария', 'last_name': 'Петрова',
            'email': 'maria@example.com',
        })
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.get_full_name(), 'Мария Петрова')
        self.assertEqual(self.teacher.email, 'maria@example.com')
        self.assertTrue(self.teacher.check_password('pass12345'))

    def test_change_password_keeps_session(self):
        response = self.client.post(self.url, {
            'change_password': '1',
            'old_password': 'pass12345',
            'new_password1': 'новый пароль 42',
            'new_password2': 'новый пароль 42',
        })
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password('новый пароль 42'))
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.teacher.pk)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_wrong_old_password_is_error(self):
        response = self.client.post(self.url, {
            'change_password': '1',
            'old_password': 'wrong',
            'new_password1': 'новый пароль 42',
            'new_password2': 'новый пароль 42',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('old_password', response.context['password_form'].errors)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password('pass12345'))


class ReviewFixesTests(TestCase):
    """Правки по обходу экранов 19.10.2026 (docs/USERS_PLAN.md, раздел 15):
    логин через точку (R04-2) и подсказка (R04-1), подписи профиля без
    двоеточий и тексты смены пароля (R46-1, R46-2), «Прогресс учеников»
    только при учениках (R08-1), «Ваш учитель — …» (R36-1)."""

    def setUp(self):
        self.admin = make_admin()
        self.teacher = make_teacher()

    def test_generate_username_joins_with_dot(self):
        from .forms import generate_username
        self.assertEqual(generate_username('Ирина', 'Смирнова'), 'smirnova.irina')
        self.assertEqual(generate_username('Петя', 'Иванов'), 'ivanov.petya')
        User.objects.create_user(username='ivanov.petya', password='x')
        self.assertEqual(generate_username('Петя', 'Иванов'), 'ivanov.petya2')
        # Пустая часть не оставляет точки; обрезка до 24 символов без хвоста
        self.assertEqual(generate_username('', 'Иванов'), 'ivanov')
        self.assertEqual(generate_username('Александра', 'Константинопольская'),
                         'konstantinopolskaya.alek')
        self.assertEqual(generate_username('', ''), 'uchenik')

    def test_join_form_username_hint(self):
        invite = TeacherInvite.objects.create(
            created_by=self.admin, expires_at=timezone.now() + timedelta(days=3))
        response = self.client.get(reverse('teacher_join', args=[invite.token]))
        self.assertContains(response, 'составится из фамилии и имени, например smirnova.irina')
        # После 0c53cde подсказка логина — placeholder, поле уходит пустым:
        # фраза «Если оставить пустым» снова точна, проверяем пример логина
        self.assertContains(response, 'smirnova.irina')
        self.assertContains(response, 'registration.js')

    def test_student_create_uses_dotted_username(self):
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('students'), {
            'first_name': 'Петя', 'last_name': 'Иванов', 'grade': 7})
        self.assertTrue(User.objects.filter(username='ivanov.petya').exists())

    def test_profile_labels_and_password_texts(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('profile'))
        self.assertContains(response, '>Имя</label>')
        self.assertContains(response, '>Текущий пароль</label>')
        self.assertContains(response, '>Новый пароль</label>')
        self.assertContains(response, '>Повторите новый пароль</label>')
        self.assertContains(response, 'От 6 до 128 символов')
        self.assertNotContains(response, 'Имя:')
        self.assertNotContains(response, 'пароль:')
        self.assertNotContains(response, 'Для подтверждения')
        self.assertNotContains(response, 'как минимум')

    def test_progress_button_only_with_students(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('students'))
        self.assertNotContains(response, 'Прогресс учеников')
        student = User.objects.create_user(username='student1', password='pass12345')
        Profile.objects.create(user=student, role=Profile.ROLE_STUDENT, teacher=self.teacher)
        response = self.client.get(reverse('students'), {'q': 'нет такого'})
        self.assertContains(response, 'Прогресс учеников')

    def test_student_registration_names_teacher(self):
        code = self.teacher.profile.student_code
        response = self.client.get(reverse('register'), {'t': code})
        self.assertContains(response, 'Ваш учитель — Иван Учителев.')
        self.assertNotContains(response, 'записываетесь')
