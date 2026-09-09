from django import forms
from django.contrib.auth.models import User

from accounts.models import Profile, StudentGroup
from worksheets.models import Worksheet

from .models import Assignment, locked_check_visibility


class AssignedStudentsWidget(forms.CheckboxSelectMultiple):
    """Блокирует учеников, которым выбранный листок уже назначен."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.assigned_ids = set()

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex, attrs)
        if str(value) in self.assigned_ids:
            option['attrs']['disabled'] = True
            option['label'] = f'{option["label"]} — уже назначено'
        return option


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
        widget=AssignedStudentsWidget)
    due_at = forms.DateTimeField(
        label='Срок сдачи', required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    check_visibility = forms.ChoiceField(
        label='Автосверка ответов', choices=Assignment.CHECK_CHOICES,
        initial=Assignment.CHECK_LIVE)
    allow_photos = forms.BooleanField(
        label='Принимать фото решений', required=False, initial=True)

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.fields['worksheet'].queryset = (
            Worksheet.visible_to(teacher).select_related('owner')
            .order_by('-updated_at'))
        self.fields['groups'].queryset = (
            StudentGroup.visible_to(teacher).select_related('teacher'))
        if teacher.is_superuser:
            self.fields['worksheet'].label_from_instance = lambda worksheet: (
                f'{worksheet.title} — '
                f'{worksheet.owner.get_full_name() or worksheet.owner.username}')
            self.fields['groups'].label_from_instance = lambda group: (
                f'{group.name} — '
                f'{group.teacher.get_full_name() or group.teacher.username}')
        self.fields['students'].queryset = (
            Profile.student_users_for(teacher)
            .select_related('profile')
            .order_by('last_name', 'first_name', 'username'))
        self.selected_worksheet = self._selected_worksheet()
        if self.selected_worksheet:
            assigned_ids = self.selected_worksheet.assignments.values_list(
                'student_id', flat=True)
            self.fields['students'].widget.assigned_ids = {
                str(pk) for pk in assigned_ids}
            locked = locked_check_visibility(self.selected_worksheet)
            if locked:
                check_field = self.fields['check_visibility']
                check_field.disabled = True
                check_field.initial = locked
                self.initial['check_visibility'] = locked
                check_field.help_text = (
                    'Уже задано ученикам — режим сверки для этого листка '
                    'изменить нельзя.')
        if not self.fields['check_visibility'].help_text:
            self.fields['check_visibility'].help_text = (
                'После первой выдачи режим для листка фиксируется. При '
                'самопроверке вы увидите, сколько раз ученик нажимал '
                '«Проверить».')

    def _selected_worksheet(self):
        """Свой листок из bound-данных или initial, без доверия к GET/POST."""
        value = (self.data.get(self.add_prefix('worksheet')) if self.is_bound
                 else self.initial.get('worksheet'))
        if isinstance(value, Worksheet):
            return self.fields['worksheet'].queryset.filter(
                pk=value.pk).first()
        value = str(value or '')
        if value.isdigit():
            return self.fields['worksheet'].queryset.filter(pk=value).first()
        return None

    def clean(self):
        cleaned = super().clean()
        groups = cleaned.get('groups')
        students = cleaned.get('students')

        student_ids = set(students.values_list('pk', flat=True)) \
            if students is not None else set()
        if groups is not None:
            student_ids.update(
                Profile.student_users_for(self.teacher)
                .filter(member_groups__in=groups)
                .values_list('pk', flat=True))
        if not student_ids:
            raise forms.ValidationError(
                'Выберите хотя бы одну группу или одного ученика.')

        cleaned['recipients'] = self.fields['students'].queryset.filter(
            pk__in=student_ids)
        return cleaned
