from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render

from assignments.models import Assignment
from worksheets.models import Worksheet

from .decorators import get_role, teacher_required
from .forms import StudentCreateForm, generate_password
from .models import Profile


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
    worksheets = Worksheet.objects.filter(owner=request.user)[:15]
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
    })


def student_dashboard(request):
    assignments = (Assignment.objects
                   .filter(student=request.user)
                   .select_related('worksheet', 'worksheet__owner')
                   .order_by('-assigned_at'))
    return render(request, 'accounts/dashboard_student.html', {
        'assignments': assignments,
    })


@teacher_required
def students(request):
    """Список учеников учителя + добавление нового."""
    new_credentials = request.session.pop('new_student_credentials', None)
    if request.method == 'POST':
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
    else:
        form = StudentCreateForm()
    student_profiles = (Profile.objects
                        .filter(teacher=request.user,
                                role=Profile.ROLE_STUDENT)
                        .select_related('user')
                        .order_by('user__last_name', 'user__first_name'))
    return render(request, 'accounts/students.html', {
        'form': form,
        'student_profiles': student_profiles,
        'new_credentials': new_credentials,
    })


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
