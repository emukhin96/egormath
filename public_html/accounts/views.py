from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from assignments.models import Assignment
from problems.models import Task
from worksheets.models import Worksheet

from core.mailing import mail_enabled

from .decorators import get_role, superuser_required, teacher_required
from .permissions import base_editor_required, catalog_tasks, is_base_editor
from .forms import (InviteUnavailable, StudentCreateForm, StudentEditForm,
                    StudentGroupForm, StudentRegistrationForm,
                    TeacherInviteForm, TeacherJoinForm,
                    TeacherPasswordChangeForm, TeacherProfileForm,
                    generate_password)
from .mailing import send_teacher_invite
from .models import Profile, StudentGroup, TeacherInvite
from .onboarding import (dashboard_onboarding, onboarding_progress,
                         shows_onboarding)


def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')


@require_http_methods(['GET', 'POST'])
def register(request):
    """Самостоятельная регистрация ученика с немедленным входом.

    ``?t=<код>`` из персональной ссылки учителя записывает ученика к нему;
    код едет дальше скрытым полем формы. Без кода — к ``default_teacher()``.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    link_invalid = False
    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except IntegrityError:
                # Защита от одновременной регистрации одинакового логина.
                form.add_error('username', 'Этот логин уже занят.')
            else:
                auth_login(request, user)
                messages.success(request, 'Аккаунт создан. Добро пожаловать!')
                return redirect('dashboard')
        # Неверный код — ошибка формы (non_field_errors), шаблон её покажет
        link_teacher = form.teacher
    else:
        # Код остаётся в скрытом поле и при неверной ссылке: отправка формы
        # повторит ту же ошибку, а не запишет ученика к другому учителю
        code = request.GET.get('t', '').strip()
        form = StudentRegistrationForm(initial={'teacher_code': code})
        link_teacher = Profile.teacher_by_student_code(code)
        link_invalid = bool(code) and link_teacher is None
    return render(request, 'accounts/register.html', {
        'form': form,
        'link_teacher': link_teacher,
        'link_invalid': link_invalid,
    })


@require_http_methods(['GET', 'POST'])
def teacher_join(request, token):
    """Регистрация учителя по приглашению.

    Неизвестный (отозванный), просроченный или погашенный токен — страница
    с объяснением без формы, не 404: ссылку открывает человек, которому
    её прислали, и ему нужно понять, что делать дальше.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    invite = (TeacherInvite.objects.filter(token=token)
              .select_related('created_by').first())
    reason = invite_unavailable_reason(invite)
    if reason:
        return render(request, 'accounts/join_unavailable.html',
                      {'reason': reason}, status=200)
    form = TeacherJoinForm(
        request.POST if request.method == 'POST' else None, invite=invite)
    if request.method == 'POST' and form.is_valid():
        try:
            user = form.save()
        except InviteUnavailable:
            # Двойная отправка одной ссылки: приглашение уже погашено
            invite.refresh_from_db()
            return render(request, 'accounts/join_unavailable.html',
                          {'reason': invite_unavailable_reason(invite)})
        except IntegrityError:
            form.add_error('username', 'Этот логин уже занят.')
        else:
            auth_login(request, user)
            # Логин мог быть составлен сервером (пустое поле, занятый
            # вариант с номером) — назвать его, чтобы учитель знал, как входить
            messages.success(
                request, f'Аккаунт создан. Ваш логин: {user.username} '
                         '(он же в профиле). Добро пожаловать!')
            # Новому учителю — чеклист «Первые шаги», не кабинет (раздел 7 плана)
            return redirect('welcome')
    return render(request, 'accounts/join.html', {
        'form': form,
        'invite': invite,
    })


def invite_unavailable_reason(invite):
    """Почему по ссылке нельзя зарегистрироваться: ключ для шаблона
    ``join_unavailable.html`` или ``None``, если приглашение действует."""
    if invite is None:
        return 'unknown'
    if invite.is_used:
        return 'used'
    if invite.is_expired:
        return 'expired'
    return None


@teacher_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    """Мини-профиль учителя: имя, фамилия, почта и смена пароля."""
    user = request.user
    profile_form = TeacherProfileForm(user=user)
    password_form = TeacherPasswordChangeForm(user)
    if request.method == 'POST' and 'change_password' in request.POST:
        password_form = TeacherPasswordChangeForm(user, request.POST)
        if password_form.is_valid():
            password_form.save()
            # Иначе смена пароля разлогинит текущую сессию
            update_session_auth_hash(request, password_form.user)
            messages.success(request, 'Пароль изменён.')
            return redirect('profile')
    elif request.method == 'POST':
        profile_form = TeacherProfileForm(request.POST, user=user)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, 'Профиль сохранён.')
            return redirect('profile')
    return render(request, 'accounts/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'teacher_profile': Profile.for_teacher(user),
        # «Первые шаги» с прогрессом — не редактору (accounts/onboarding.py)
        'onboarding': onboarding_progress(request) if shows_onboarding(user) else None,
    })


@teacher_required
def welcome(request):
    """«Первые шаги»: чеклист нового учителя с прогрессом по данным
    (accounts/onboarding.py). Сюда ведёт редирект после регистрации по
    приглашению; повторно — из кабинета и профиля."""
    return render(request, 'accounts/welcome.html', {
        'onboarding': onboarding_progress(request),
        'shows_onboarding': shows_onboarding(request.user),
    })


@teacher_required
@require_POST
def onboarding_hide(request):
    """Кнопка «Скрыть» на карточке «Первые шаги» в кабинете: запоминает
    момент в ``Profile.onboarding_done_at``; сама страница остаётся
    доступной из профиля."""
    profile = Profile.for_teacher(request.user)
    profile.onboarding_done_at = timezone.now()
    profile.save(update_fields=['onboarding_done_at'])
    messages.success(request, 'Карточка «Первые шаги» скрыта — страница '
                              'остаётся доступной из профиля.')
    return redirect('dashboard')


def teacher_users():
    """Все учителя сайта вместе с суперпользователями без профиля."""
    return (User.objects.filter(
        Q(profile__role=Profile.ROLE_TEACHER) | Q(is_superuser=True))
        .distinct())


@superuser_required
@require_http_methods(['GET', 'POST'])
def teachers(request):
    """Учителя сайта и приглашения — только суперпользователю."""
    new_credentials = request.session.pop('new_teacher_credentials', None)
    new_invite = request.session.pop('new_invite', None)
    invite_form = TeacherInviteForm()
    if request.method == 'POST':
        invite_form = TeacherInviteForm(request.POST)
        if invite_form.is_valid():
            invite = invite_form.save(created_by=request.user)
            # Ссылка показывается один раз — после редиректа, как пароль;
            # id и почта — для кнопки «Отправить письмом» в том же блоке
            request.session['new_invite'] = {
                'id': invite.pk,
                'note': invite.note,
                'email': invite.email,
                'url': request.build_absolute_uri(
                    reverse('teacher_join', args=[invite.token])),
            }
            messages.success(request, 'Приглашение создано.')
            return redirect('teachers')
    teacher_list = (teacher_users().select_related('profile')
                    .annotate(
                        students_count=Count(
                            'students', distinct=True,
                            filter=Q(students__role=Profile.ROLE_STUDENT)),
                        worksheets_count=Count('worksheets', distinct=True))
                    .order_by('-is_superuser', 'last_name', 'first_name',
                              'username'))
    # Ссылка у непогашенного приглашения показывается и в списке (R03-1):
    # суперпользователь и так её владелец, а окно с разовым показом легко закрыть
    invites = list(TeacherInvite.pending().select_related('created_by'))
    for invite in invites:
        invite.url = request.build_absolute_uri(
            reverse('teacher_join', args=[invite.token]))
    return render(request, 'accounts/teachers.html', {
        'teacher_list': teacher_list,
        'invites': invites,
        'invite_form': invite_form,
        'new_credentials': new_credentials,
        'new_invite': new_invite,
    })


def _managed_teacher(request, user_id):
    """Учитель (или суперпользователь), которым распоряжается администратор."""
    return get_object_or_404(teacher_users().select_related('profile'),
                             pk=user_id)


@superuser_required
@require_POST
def teacher_reset_password(request, user_id):
    teacher = _managed_teacher(request, user_id)
    if teacher.pk == request.user.pk:
        # set_password без update_session_auth_hash разлогинил бы
        # администратора, а новый пароль он бы уже не увидел
        messages.error(request, 'Свой пароль меняйте на странице «Профиль».')
        return redirect('teachers')
    password = generate_password()
    teacher.set_password(password)
    teacher.save(update_fields=['password'])
    request.session['new_teacher_credentials'] = {
        'name': teacher.get_full_name() or teacher.username,
        'username': teacher.username,
        'password': password,
    }
    messages.success(
        request, f'Пароль учителя {teacher.get_full_name() or teacher.username} сброшен.')
    return redirect('teachers')


@superuser_required
@require_POST
def teacher_toggle_active(request, user_id):
    teacher = _managed_teacher(request, user_id)
    if teacher.pk == request.user.pk:
        messages.error(request, 'Нельзя отключить самого себя.')
        return redirect('teachers')
    teacher.is_active = not teacher.is_active
    teacher.save(update_fields=['is_active'])
    name = teacher.get_full_name() or teacher.username
    messages.success(
        request, f'Учитель {name} {"включён" if teacher.is_active else "отключён"}.')
    return redirect('teachers')


@superuser_required
@require_POST
def teacher_toggle_base_editor(request, user_id):
    teacher = _managed_teacher(request, user_id)
    if teacher.is_superuser:
        messages.error(request, 'У администратора право править базу есть всегда.')
        return redirect('teachers')
    # Явное значение, а не переключение: повторная отправка той же формы
    # (двойной клик, обновление страницы) не вернёт право обратно
    profile = teacher.profile
    profile.base_editor = request.POST.get('base_editor') == '1'
    profile.save(update_fields=['base_editor'])
    name = teacher.get_full_name() or teacher.username
    messages.success(request, (
        f'{name} теперь правит общие задачи.' if profile.base_editor
        else f'{name} больше не правит общие задачи.'))
    return redirect('teachers')


@superuser_required
@require_POST
def invite_revoke(request, invite_id):
    invite = get_object_or_404(TeacherInvite, pk=invite_id, used_at__isnull=True)
    invite.delete()
    messages.success(request, 'Приглашение отозвано.')
    return redirect('teachers')


@superuser_required
@require_POST
def invite_send(request, invite_id):
    """«Отправить письмом» на странице «Учителя»: ссылка-приглашение на
    почту из приглашения (accounts/mailing.py). Только непогашенные и не
    просроченные; без настроенной почты кнопки в шаблоне нет, прямой POST —
    сообщение об ошибке, ссылку по-прежнему копируют вручную."""
    invite = get_object_or_404(
        TeacherInvite.pending().select_related('created_by'), pk=invite_id)
    url = request.build_absolute_uri(reverse('teacher_join', args=[invite.token]))
    if not invite.email:
        messages.error(request, 'У приглашения не указана почта — скопируйте ссылку и отправьте сами.')
    elif not mail_enabled():
        messages.error(request, 'Почта на сайте не настроена — скопируйте ссылку и отправьте сами.')
    elif send_teacher_invite(invite, url):
        messages.success(request, f'Письмо отправлено на {invite.email}.')
    else:
        messages.error(
            request,
            f'Письмо на {invite.email} не отправлено: сервер почты не принял. '
            'Подробности в логе сайта; пока скопируйте ссылку и отправьте сами.')
    return redirect('teachers')


@base_editor_required
@require_POST
def task_list_prefs(request):
    """Тумблер каталога «Показывать задачи других учителей» (решение 1 плана
    пользователей): хранится в профиле редактора, после сохранения — назад
    на тот же URL каталога с его фильтрами. Явное значение, не инверсия:
    повторная отправка формы ничего не переключит обратно."""
    profile = Profile.for_teacher(request.user)
    profile.show_foreign_tasks = request.POST.get('show_foreign_tasks') == '1'
    profile.save(update_fields=['show_foreign_tasks'])
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('task_list')
    return redirect(next_url)


@login_required
def dashboard(request):
    role = get_role(request.user)
    if role == Profile.ROLE_TEACHER:
        return teacher_dashboard(request)
    if role == Profile.ROLE_STUDENT:
        return student_dashboard(request)
    messages.error(
        request,
        'У вашего пользователя не задана роль. Обратитесь к администратору.')
    return render(request, 'accounts/no_role.html')


def teacher_dashboard(request):
    worksheets = (Worksheet.visible_to(request.user).select_related('owner')
                  .annotate(items_total=Count('items'))[:15])
    pending = (Assignment.visible_to(request.user)
               .filter(status=Assignment.STATUS_SUBMITTED)
               .select_related('worksheet', 'worksheet__owner', 'student')
               .order_by('submitted_at'))
    reviewed = (Assignment.visible_to(request.user)
                .filter(status=Assignment.STATUS_REVIEWED)
                .select_related('worksheet', 'worksheet__owner', 'student')
                .order_by('-reviewed_at')[:10])
    context = {
        'worksheets': worksheets,
        'pending': pending,
        'reviewed': reviewed,
        'worksheets_total': Worksheet.visible_to(request.user).count(),
        'students_total': Profile.students_for(request.user).count(),
        'tasks_total': catalog_tasks(request.user).count(),
        'proposals': None,
        # Карточка «Первые шаги» — не редактору, пока не скрыта и не пройдена
        'onboarding': dashboard_onboarding(request),
    }
    if is_base_editor(request.user):
        # Очередь предложений исправлений — последние новые, как «Ожидают
        # проверки»; счётчик — из контекст-процессора shell.
        from problems.models import TaskProposal
        context['proposals'] = (
            TaskProposal.objects.filter(status=TaskProposal.STATUS_NEW)
            .select_related('task', 'author')[:5])
    return render(request, 'accounts/dashboard_teacher.html', context)


def student_dashboard(request):
    assignments = list(Assignment.objects
                       .filter(student=request.user)
                       .select_related('worksheet', 'worksheet__owner')
                       .order_by('-assigned_at'))
    from independentworks.integration import student_assignments
    assignments += student_assignments(request.user)
    assignments.sort(key=lambda a: a.assigned_at, reverse=True)
    kind = request.GET.get("kind", "")
    if kind in ("ordinary", "independent"):
        assignments = [a for a in assignments if getattr(a, "kind", "ordinary") == kind]
    # Группы по статусу: сначала то, что требует действия ученика. Внутри
    # группы — свежие сверху, как в общем списке: «срочное» не поднимаем
    # вверх, а подсвечиваем строку (attention), иначе порядок выглядит
    # случайным и новое задание теряется в середине таблицы.
    todo = [a for a in assignments if a.is_editable_by_student]
    # Текущее задание боковой панели — то, что нужно делать раньше всего
    current = min(todo, key=lambda a: (
        0 if getattr(a, "active", False) else 1,
        0 if a.status == Assignment.STATUS_RETURNED else 1,
        0 if a.is_overdue else 1,
        a.due_at.timestamp() if a.due_at else float('inf'),
        -a.assigned_at.timestamp(),
    ), default=None)
    # Подсветка: текущее, идёт таймер, возвращено, есть срок (впереди или
    # уже просрочен — такое тем более сдать) или выдано за последнюю неделю;
    # старые задания без срока — обычной строкой
    week_ago = timezone.now() - timedelta(days=7)
    for a in todo:
        a.attention = bool(
            a is current or getattr(a, "active", False)
            or a.status == Assignment.STATUS_RETURNED
            or a.due_at
            or a.assigned_at >= week_ago)
    if current is not None and getattr(current, 'kind', 'ordinary') == 'ordinary':
        # «Отвечено N/M» на карточке «Сейчас»; у самостоятельной счёт уже
        # посчитан в independentworks.integration
        submissions = current.submissions.prefetch_related('parts', 'photos')
        current.answered = sum(1 for sub in submissions if not sub.is_empty)
        current.total = current.visible_task_count()
    submitted = [a for a in assignments
                 if a.status == Assignment.STATUS_SUBMITTED]
    reviewed = [a for a in assignments
                if a.status == Assignment.STATUS_REVIEWED]
    return render(request, 'accounts/dashboard_student.html', {
        'assignments': assignments,
        'current': current,
        'todo': todo,
        # Список «Нужно сдать» без текущего: оно уже на карточке «Сейчас»
        'todo_rest': [a for a in todo if a is not current],
        'submitted': submitted,
        'reviewed': reviewed,
        'closed_unstarted': [a for a in assignments if getattr(a, 'closed_unstarted', False)],
        'kind': kind,
        'overdue_total': sum(1 for a in todo if a.is_overdue),
        'now': timezone.now().isoformat(),
    })


@teacher_required
def students(request):
    """Список учеников: компактное добавление, поиск и группы."""
    new_credentials = request.session.pop('new_student_credentials', None)
    form = StudentCreateForm()
    group_form = StudentGroupForm(teacher=request.user)
    if request.method == 'POST':
        if 'create_group' in request.POST:
            group_form = StudentGroupForm(request.POST, teacher=request.user)
            if group_form.is_valid():
                group = group_form.save()
                messages.success(request, f'Группа «{group.name}» создана.')
                return redirect('students')
        else:
            form = StudentCreateForm(request.POST)
            if form.is_valid():
                user, password = form.save(teacher=request.user)
                request.session['new_student_credentials'] = {
                    'name': user.get_full_name(),
                    'username': user.username,
                    'password': password,
                }
                messages.success(request, f'Ученик {user.get_full_name()} создан.')
                return redirect('students')
    q = request.GET.get('q', '').strip()
    group_id = request.GET.get('group', '').strip()
    teacher_id = request.GET.get('teacher', '').strip()
    visible_groups = (StudentGroup.visible_to(request.user)
                      .select_related('teacher'))
    student_profiles = Profile.students_for(request.user).select_related('user')
    if q:
        student_profiles = student_profiles.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q))
    if request.user.is_superuser and teacher_id.isdigit():
        student_profiles = student_profiles.filter(teacher_id=teacher_id)
        filter_groups = visible_groups.filter(teacher_id=teacher_id)
    else:
        teacher_id = ''
        filter_groups = visible_groups

    current_group = None
    if group_id == 'ungrouped':
        visible_group_ids = filter_groups.values('pk')
        student_profiles = student_profiles.exclude(
            user__member_groups__in=visible_group_ids)
    elif group_id.isdigit():
        current_group = filter_groups.filter(pk=group_id).first()
        if current_group:
            student_profiles = student_profiles.filter(
                user__member_groups=current_group)
        else:
            group_id = ''

    group_order = (('teacher__last_name', 'teacher__first_name', 'name')
                   if request.user.is_superuser else ('name',))
    groups = filter_groups.prefetch_related('students').order_by(*group_order)
    bulk_groups = visible_groups.order_by(*group_order)
    student_profiles = (student_profiles.prefetch_related(Prefetch(
        'user__member_groups', queryset=visible_groups.order_by('name'),
        to_attr='visible_groups'))
        .distinct().order_by(
            'user__last_name', 'user__first_name', 'user__username'))
    # Без фильтра по группе список делится на блоки по группам — в общем
    # списке иначе трудно найти своих; при выборе группы блок один. Блоки —
    # по тем же группам, что фильтр (filter_groups): при ?teacher=X у
    # суперпользователя группа чужого учителя блоком не становится, а
    # «Без группы» совпадает с фильтром group=ungrouped.
    student_sections = (None if current_group or group_id == 'ungrouped'
                        else _student_sections(student_profiles, groups))
    teacher_choices = []
    if request.user.is_superuser:
        teacher_choices = (User.objects.filter(
            Q(profile__role=Profile.ROLE_TEACHER) | Q(is_superuser=True))
            .distinct().order_by('last_name', 'first_name', 'username'))
    student_code = Profile.for_teacher(request.user).student_code
    return render(request, 'accounts/students.html', {
        'form': form,
        'group_form': group_form,
        'registration_url': request.build_absolute_uri(
            f"{reverse('register')}?t={student_code}"),
        'student_profiles': student_profiles,
        # Кнопка «Прогресс учеников» — только когда ученики есть (R08-1),
        # независимо от поиска и фильтра по группе
        'has_students': Profile.students_for(request.user).exists(),
        'student_sections': student_sections,
        'groups': groups,
        'bulk_groups': bulk_groups,
        'current_group': current_group,
        'q': q,
        'group_filter': group_id,
        'teacher_filter': teacher_id,
        'teacher_choices': teacher_choices,
        'new_credentials': new_credentials,
    })


def _student_sections(profiles, groups):
    """Ученики блоками по группам в порядке ``groups``, «без группы» — последним.

    Ученик из нескольких групп виден в каждой; ``rows`` — пары (профиль,
    другие его группы), группа блока в строке не повторяется. Если ни у кого
    нет группы — ``None``, список выводится одной таблицей.
    """
    sections = {group.pk: {'group': group, 'profiles': []} for group in groups}
    ungrouped = []
    for profile in profiles:
        own = [group for group in profile.user.visible_groups
               if group.pk in sections]
        for group in own:
            sections[group.pk]['profiles'].append(profile)
        if not own:
            ungrouped.append(profile)
    result = [section for section in sections.values() if section['profiles']]
    if not result:
        return None
    for section in result:
        section['rows'] = [
            (profile, [g for g in profile.user.visible_groups
                       if g.pk != section['group'].pk])
            for profile in section['profiles']]
    if ungrouped:
        result.append({'group': None, 'profiles': ungrouped,
                       'rows': [(profile, []) for profile in ungrouped]})
    return result


def _students_redirect(data):
    params = {
        key: data.get(key, '').strip()
        for key in ('q', 'group', 'teacher') if data.get(key, '').strip()
    }
    url = reverse('students')
    return redirect(f'{url}?{urlencode(params)}' if params else url)


@teacher_required
@require_POST
def students_bulk_groups(request):
    """Добавить, убрать или переместить выбранных учеников."""
    ids = {int(value) for value in request.POST.getlist('ids')
           if value.isdigit()}
    profiles = list(Profile.students_for(request.user).select_related('user')
                    .filter(user_id__in=ids))
    if not ids or len(profiles) != len(ids):
        messages.error(request, 'Выберите доступных учеников.')
        return _students_redirect(request.POST)

    groups = StudentGroup.visible_to(request.user)
    action = request.POST.get('action', '')
    group_id = request.POST.get('target_group', '')
    group = groups.filter(pk=group_id).first() if group_id.isdigit() else None
    source_id = request.POST.get('source_group', '')
    source = groups.filter(pk=source_id).first() if source_id.isdigit() else None
    if action not in ('add', 'remove', 'move') or group is None:
        messages.error(request, 'Выберите действие и группу.')
        return _students_redirect(request.POST)
    if action == 'move' and (source is None or source.pk == group.pk):
        messages.error(request, 'Для перемещения выберите другую группу.')
        return _students_redirect(request.POST)

    students_to_change = [profile.user for profile in profiles]
    with transaction.atomic():
        if action == 'add':
            group.students.add(*students_to_change)
            message = f'Ученики добавлены в группу «{group.name}».'
        elif action == 'remove':
            group.students.remove(*students_to_change)
            message = f'Ученики удалены из группы «{group.name}».'
        else:
            if source.students.filter(pk__in=ids).count() != len(ids):
                messages.error(request, (
                    'Не все выбранные ученики состоят в исходной группе.'))
                return _students_redirect(request.POST)
            source.students.remove(*students_to_change)
            group.students.add(*students_to_change)
            message = f'Ученики перемещены в группу «{group.name}».'
    messages.success(request, message)
    return _students_redirect(request.POST)


@teacher_required
def student_edit(request, user_id):
    """Правка данных ученика через веб-интерфейс."""
    profile = get_object_or_404(
        Profile.students_for(request.user).select_related('user'),
        user_id=user_id)
    if request.method == 'POST':
        form = StudentEditForm(request.POST, teacher=request.user)
        if form.is_valid():
            user = form.save(profile)
            messages.success(
                request, f'Данные ученика {user.get_full_name()} сохранены.')
            return redirect('students')
    else:
        form = StudentEditForm(teacher=request.user, initial={
            'first_name': profile.user.first_name,
            'last_name': profile.user.last_name,
            'grade': profile.grade,
            'groups': profile.user.member_groups.filter(
                pk__in=StudentGroup.visible_to(request.user)),
        })
    return render(request, 'accounts/student_edit.html', {
        'form': form,
        'profile': profile,
    })


@teacher_required
@require_POST
def group_delete(request, group_id):
    group = get_object_or_404(
        StudentGroup.visible_to(request.user), pk=group_id)
    name = group.name
    group.delete()
    messages.success(request, f'Группа «{name}» удалена (ученики остались).')
    return redirect('students')


@teacher_required
@require_POST
def group_rename(request, group_id):
    group = get_object_or_404(
        StudentGroup.visible_to(request.user), pk=group_id)
    form = StudentGroupForm(request.POST, teacher=request.user, instance=group)
    if form.is_valid():
        form.save()
        messages.success(request, 'Группа переименована.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('students')


@teacher_required
def reset_student_password(request, user_id):
    profile = get_object_or_404(
        Profile.students_for(request.user), user_id=user_id)
    if request.method == 'POST':
        password = generate_password()
        profile.user.set_password(password)
        profile.user.save()
        request.session['new_student_credentials'] = {
            'name': profile.user.get_full_name(),
            'username': profile.user.username,
            'password': password,
        }
        messages.success(
            request, f'Пароль ученика {profile.user.get_full_name()} сброшен.')
    return redirect('students')
