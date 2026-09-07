from django import forms
from django.contrib.auth.models import User

from accounts.models import Profile, StudentGroup
from worksheets.models import Worksheet

from .models import Assignment, locked_check_visibility


class StudentChoiceField(forms.ModelMultipleChoiceField):
    """Ученики с понятной подписью в мастере выдачи."""

    def label_from_instance(self, user):
        name = user.get_full_name() or user.username
        grade = getattr(user.profile, 'grade', None)
        return f'{name} · {grade} класс' if grade else name


class AssignmentCreateForm(forms.Form):
    """Единая форма выдачи листка группам и отдельным ученикам."""

    worksheet = forms.ModelChoiceField(
        label='Листок', queryset=Worksheet.objects.none())
    groups = forms.ModelMultipleChoiceField(
        label='Группы', required=False,
        queryset=StudentGroup.objects.none(),
        widget=forms.CheckboxSelectMultiple)
    students = StudentChoiceField(
        label='Отдельные ученики', required=False,
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple)
    due_at = forms.DateTimeField(
        label='Срок сдачи', required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    check_visibility = forms.ChoiceField(
        label='Автосверка ответов', choices=Assignment.CHECK_CHOICES,
        initial=Assignment.CHECK_TEACHER)
    allow_photos = forms.BooleanField(
        label='Принимать фото решений', required=False, initial=True)

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.fields['worksheet'].queryset = (
            Worksheet.objects.filter(owner=teacher).order_by('-updated_at'))
        self.fields['groups'].queryset = teacher.owned_groups.all()
        self.fields['students'].queryset = (
            User.objects.filter(
                profile__teacher=teacher,
                profile__role=Profile.ROLE_STUDENT)
            .select_related('profile')
            .order_by('last_name', 'first_name', 'username'))

    def clean(self):
        cleaned = super().clean()
        worksheet = cleaned.get('worksheet')
        groups = cleaned.get('groups')
        students = cleaned.get('students')

        student_ids = set(students.values_list('pk', flat=True)) \
            if students is not None else set()
        if groups is not None:
            student_ids.update(
                User.objects.filter(
                    member_groups__in=groups,
                    profile__teacher=self.teacher,
                    profile__role=Profile.ROLE_STUDENT)
                .values_list('pk', flat=True))
        if not student_ids:
            raise forms.ValidationError(
                'Выберите хотя бы одну группу или одного ученика.')

        cleaned['recipients'] = self.fields['students'].queryset.filter(
            pk__in=student_ids)
        if worksheet:
            locked = locked_check_visibility(worksheet)
            if locked:
                cleaned['check_visibility'] = locked
                cleaned['locked_check_visibility'] = locked
        return cleaned
