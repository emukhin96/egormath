from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from assignments.models import Assignment
from problems.models import Task
from worksheets.models import Worksheet

from .decorators import get_role, teacher_required
from .forms import (StudentCreateForm, StudentEditForm, StudentGroupForm,
                    generate_password)
from .models import Profile, StudentGroup


def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')


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
    worksheets = (Worksheet.objects
                  .filter(owner=request.user)
                  .annotate(items_total=Count('items'))[:15])
    pending = (Assignment.objects
               .filter(worksheet__owner=request.user,
                       status=Assignment.STATUS_SUBMITTED)
               .select_related('worksheet', 'student')
               .order_by('submitted_at'))
    reviewed = (Assignment.objects
                .filter(worksheet__owner=request.user,
                        status=Assignment.STATUS_REVIEWED)
                .select_related('worksheet', 'student')
                .order_by('-reviewed_at')[:10])
    return render(request, 'accounts/dashboard_teacher.html', {
        'worksheets': worksheets,
        'pending': pending,
        'reviewed': reviewed,
        'worksheets_total': Worksheet.objects.filter(
            owner=request.user).count(),
        'students_total': Profile.objects.filter(
            teacher=request.user, role=Profile.ROLE_STUDENT).count(),
        'tasks_total': Task.objects.filter(
            variant_of__isnull=True).count(),
    })


def student_dashboard(request):
    assignments = list(Assignment.objects
                       .filter(student=request.user)
                       .select_related('worksheet', 'worksheet__owner')
                       .order_by('-assigned_at'))
    current = next(
        (a for a in assignments if a.is_editable_by_student), None)
    return render(request, 'accounts/dashboard_student.html', {
        'assignments': assignments,
        'current': current,
        'rest': [a for a in assignments if a != current],
    })


@teacher_required
def students(request):
    """Список учеников учителя: добавление, группы, фильтр по группе."""
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
    student_profiles = (Profile.objects
                        .filter(teacher=request.user,
                                role=Profile.ROLE_STUDENT)
                        .select_related('user')
                        .prefetch_related('user__member_groups')
                        .order_by('user__last_name', 'user__first_name'))
    groups = request.user.owned_groups.prefetch_related('students')
    current_group = None
    group_id = request.GET.get('group')
    if group_id:
        current_group = groups.filter(pk=group_id).first()
        if current_group:
            student_profiles = student_profiles.filter(
                user__member_groups=current_group)
    return render(request, 'accounts/students.html', {
        'form': form,
        'group_form': group_form,
        'student_profiles': student_profiles,
        'groups': groups,
        'current_group': current_group,
        'new_credentials': new_credentials,
    })


@teacher_required
def student_edit(request, user_id):
    """Правка данных ученика через веб-интерфейс."""
    profile = get_object_or_404(
        Profile.objects.select_related('user'),
        user_id=user_id, teacher=request.user, role=Profile.ROLE_STUDENT)
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
            'groups': profile.user.member_groups.filter(teacher=request.user),
        })
    return render(request, 'accounts/student_edit.html', {
        'form': form,
        'profile': profile,
    })


@teacher_required
@require_POST
def group_delete(request, group_id):
    group = get_object_or_404(
        StudentGroup, pk=group_id, teacher=request.user)
    name = group.name
    group.delete()
    messages.success(request, f'Группа «{name}» удалена (ученики остались).')
    return redirect('students')


@teacher_required
@require_POST
def group_rename(request, group_id):
    group = get_object_or_404(
        StudentGroup, pk=group_id, teacher=request.user)
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
        Profile, user_id=user_id, teacher=request.user,
        role=Profile.ROLE_STUDENT)
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
