"""«Первые шаги» нового учителя (docs/USERS_PLAN.md, раздел 7; PR 4).

Прогресс чеклиста считается по данным (accounts/onboarding.py), после
регистрации по приглашению учитель попадает на ``/accounts/welcome/``,
карточка в кабинете скрывается кнопкой или сама, пустые состояния ведут к
следующему шагу, справка для учителей открывается, подсказка на общей
задаче показывается только приглашённому учителю в контексте листка.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from assignments.models import Assignment
from problems.models import Task
from problems.tests import make_invited_teacher, make_student, make_teacher
from worksheets.models import Worksheet, WorksheetItem

from .models import Profile, TeacherInvite


class OnboardingBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            'root', password='x', first_name='Егор', last_name='Мухин')
        self.editor = make_teacher('editor')
        self.guest = make_invited_teacher('guest')

    def progress(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('welcome')).context['onboarding']

    def give_assignment(self, teacher):
        """Ученик, листок и выданное задание — все три шага после имени."""
        student = make_student(teacher, f'pupil-{teacher.username}')
        sheet = Worksheet.objects.create(title='Первый листок', owner=teacher)
        Assignment.objects.create(worksheet=sheet, student=student,
                                  assigned_by=teacher)
        return student, sheet


class ProgressTests(OnboardingBase):
    def test_progress_follows_data(self):
        progress = self.progress(self.guest)
        self.assertEqual(progress['steps'], {
            'name': True, 'students': False, 'worksheet': False,
            'assignment': False})
        self.assertEqual((progress['done'], progress['total']), (1, 4))
        self.assertEqual(progress['percent'], 25)
        self.assertFalse(progress['complete'])
        self.assertFalse(progress['hidden'])
        self.assertIn(f"?t={self.guest.profile.student_code}",
                      progress['registration_url'])

        make_student(self.guest, 'pupil')
        progress = self.progress(self.guest)
        self.assertTrue(progress['steps']['students'])
        self.assertEqual(progress['done'], 2)

        sheet = Worksheet.objects.create(title='Листок', owner=self.guest)
        progress = self.progress(self.guest)
        self.assertTrue(progress['steps']['worksheet'])
        self.assertFalse(progress['complete'])

        Assignment.objects.create(
            worksheet=sheet, student=User.objects.get(username='pupil'),
            assigned_by=self.guest)
        progress = self.progress(self.guest)
        self.assertTrue(progress['steps']['assignment'])
        self.assertEqual(progress['done'], 4)
        self.assertTrue(progress['complete'])

    def test_name_step_needs_both_names(self):
        nameless = make_invited_teacher('nameless')
        nameless.last_name = ''
        nameless.save()
        progress = self.progress(nameless)
        self.assertFalse(progress['steps']['name'])
        self.assertEqual(progress['done'], 0)

    def test_foreign_data_does_not_count(self):
        """Чужие ученики, листки и задания прогресс гостя не двигают."""
        self.give_assignment(self.editor)
        progress = self.progress(self.guest)
        self.assertEqual(progress['done'], 1)

    def test_steps_rendered_with_links(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('welcome'))
        self.assertContains(response, 'Первые шаги')
        for name in ('profile', 'students', 'collection_list',
                     'worksheet_create', 'assignment_create', 'help_teachers'):
            self.assertContains(response, reverse(name))
        self.assertContains(response, 'data-copy=')
        self.assertContains(response, 'Как устроены задачи')
        self.assertContains(response, 'локальную копию')


class WelcomeAccessTests(OnboardingBase):
    def test_join_redirects_to_welcome(self):
        invite = TeacherInvite.objects.create(created_by=self.admin, note='Новый')
        response = self.client.post(
            reverse('teacher_join', args=[invite.token]), {
                'first_name': 'Мария', 'last_name': 'Петрова',
                'username': 'petrova', 'password1': 'надёжный пароль 7',
                'password2': 'надёжный пароль 7', 'email': ''})
        self.assertRedirects(response, reverse('welcome'))
        response = self.client.get(reverse('welcome'))
        self.assertContains(response, 'Первые шаги')
        self.assertEqual(response.context['onboarding']['done'], 1)

    def test_only_teachers_open_welcome(self):
        response = self.client.get(reverse('welcome'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])
        student = make_student(self.editor)
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse('welcome')).status_code, 403)
        for user in (self.guest, self.editor, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('welcome')).status_code, 200)


class DashboardCardTests(OnboardingBase):
    def test_card_only_for_invited_teacher(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertIsNotNone(response.context['onboarding'])
        self.assertContains(response, 'onboarding-card')
        self.assertContains(response, reverse('onboarding_hide'))
        self.assertContains(response, 'выполнено 1 из 4')
        # Суперпользователю и редактору карточка не нужна
        for user in (self.admin, self.editor):
            self.client.force_login(user)
            response = self.client.get(reverse('dashboard'))
            self.assertIsNone(response.context['onboarding'])
            self.assertNotContains(response, 'onboarding-card')
            self.assertNotContains(response, reverse('onboarding_hide'))

    def test_hide_button_stores_timestamp(self):
        self.client.force_login(self.guest)
        response = self.client.post(reverse('onboarding_hide'))
        # Без fetch_redirect_response: иначе сообщение-тост прочитает сам assert
        self.assertRedirects(response, reverse('dashboard'),
                             fetch_redirect_response=False)
        self.guest.profile.refresh_from_db()
        self.assertIsNotNone(self.guest.profile.onboarding_done_at)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'onboarding-card')
        # Подтверждение — тост, не плашка
        self.assertContains(response, 'ws-toast-src')
        self.assertContains(response, 'Первые шаги» скрыта')
        # Страница остаётся доступной: из панели кабинета и из профиля
        self.assertContains(response, reverse('welcome'))
        response = self.client.get(reverse('profile'))
        self.assertContains(response, reverse('welcome'))
        self.assertContains(response, 'Карточка в кабинете скрыта')
        self.assertEqual(self.client.get(reverse('welcome')).status_code, 200)

    def test_hide_requires_post_and_teacher(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse('onboarding_hide')).status_code, 405)
        student = make_student(self.editor)
        self.client.force_login(student)
        self.assertEqual(self.client.post(reverse('onboarding_hide')).status_code, 403)

    def test_card_hides_itself_after_first_assignment(self):
        self.give_assignment(self.guest)
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertIsNone(response.context['onboarding'])
        self.assertNotContains(response, 'onboarding-card')
        self.guest.profile.refresh_from_db()
        self.assertIsNone(self.guest.profile.onboarding_done_at)
        # Сама страница по-прежнему открывается и показывает полный прогресс
        progress = self.progress(self.guest)
        self.assertTrue(progress['complete'])
        self.assertEqual(progress['done'], 4)

    def test_profile_card_not_for_editors(self):
        self.client.force_login(self.guest)
        self.assertContains(self.client.get(reverse('profile')), 'Первые шаги и справка')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('profile'))
        self.assertIsNone(response.context['onboarding'])
        self.assertNotContains(response, 'Первые шаги и справка')


class EmptyStateTests(OnboardingBase):
    def test_students_page_points_to_next_step(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('students'))
        self.assertContains(response, 'Учеников пока нет')
        self.assertContains(response, reverse('worksheet_list'))
        self.assertContains(response, reverse('welcome'))
        # Редактору ссылка на «Первые шаги» не нужна
        self.client.force_login(self.editor)
        response = self.client.get(reverse('students'))
        self.assertContains(response, 'Учеников пока нет')
        self.assertNotContains(response, reverse('welcome'))

    def test_students_page_with_filters_keeps_old_text(self):
        make_student(self.guest, 'pupil')
        self.client.force_login(self.guest)
        response = self.client.get(reverse('students') + '?q=никого')
        self.assertContains(response, 'Ученики не найдены')
        self.assertNotContains(response, 'Учеников пока нет')

    def test_worksheet_list_points_to_collections_and_assignment(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('worksheet_list'))
        self.assertContains(response, 'Листков пока нет')
        for name in ('collection_list', 'worksheet_create', 'assignment_create', 'welcome'):
            self.assertContains(response, reverse(name))
        response = self.client.get(reverse('worksheet_list') + '?grade=8')
        self.assertContains(response, 'Листков не найдено')
        self.assertNotContains(response, 'Листков пока нет')

    def test_assignment_list_points_to_students_and_worksheets(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('assignment_list') + '?kind=ordinary')
        self.assertContains(response, 'Заданий пока нет')
        for name in ('assignment_create', 'students', 'worksheet_list', 'welcome'):
            self.assertContains(response, reverse(name))
        response = self.client.get(reverse('assignment_list') + '?kind=ordinary&status=submitted')
        self.assertContains(response, 'Работы не найдены')

    @override_settings(INDEPENDENT_WORKS_ENABLED=True)
    def test_independent_catalog_points_to_create(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('independentworks:catalog'))
        self.assertContains(response, 'Самостоятельных пока нет')
        self.assertContains(response, reverse('independentworks:create'))
        self.assertContains(response, reverse('welcome'))

    def test_dashboard_worksheets_empty_state(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Листков пока нет')
        self.assertContains(response, reverse('collection_list'))
        self.assertContains(response, reverse('worksheet_create'))


class HelpPageTests(OnboardingBase):
    def test_help_opens_for_teachers_only(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('help_teachers'))
        self.assertContains(response, 'Справка для учителей')
        self.assertContains(response, 'Локальные копии')
        self.assertContains(response, 'Предложения исправлений')
        self.assertContains(response, 'Почему меню «AI» неактивно')
        self.assertContains(response, reverse('welcome'))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('help_teachers')).status_code, 200)
        student = make_student(self.editor)
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse('help_teachers')).status_code, 403)

    def test_footer_link_for_teachers(self):
        for user in (self.guest, self.admin):
            self.client.force_login(user)
            self.assertContains(self.client.get(reverse('dashboard')), reverse('help_teachers'))
        student = make_student(self.editor)
        self.client.force_login(student)
        self.assertNotContains(self.client.get(reverse('dashboard')), reverse('help_teachers'))


class SharedTaskHintTests(OnboardingBase):
    def setUp(self):
        super().setUp()
        self.shared = Task.new_for(self.editor, text_latex='Общая задача')
        self.assertTrue(self.shared.is_shared)

    def card_url(self, owner):
        sheet = Worksheet.objects.create(title='Листок', owner=owner)
        item = WorksheetItem.objects.create(worksheet=sheet, task=self.shared, order=10)
        return reverse('task_detail', args=[self.shared.pk]) + f'?worksheet={sheet.pk}&item={item.pk}'

    def test_hint_for_invited_teacher_in_worksheet(self):
        self.client.force_login(self.guest)
        response = self.client.get(self.card_url(self.guest))
        self.assertContains(response, 'data-shared-task-hint')
        self.assertContains(response, 'локальную копию для листка')
        self.assertContains(response, 'data-hint-close')
        # Без листка карточка только для чтения — её объясняет постоянный блок
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertNotContains(response, 'data-shared-task-hint')
        self.assertContains(response, 'problem-base-locked')

    def test_no_hint_for_editor(self):
        self.client.force_login(self.editor)
        response = self.client.get(self.card_url(self.editor))
        self.assertNotContains(response, 'data-shared-task-hint')
