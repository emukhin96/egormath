from django import forms
from django.contrib.auth.models import User

from accounts.models import Profile, StudentGroup
from worksheets.models import Worksheet
from workaudit.clipboard import RESTRICT_LABEL, SWAP_HELP, SWAP_LABEL

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
        initial=Assignment.CHECK_LIVE,
        help_text='По умолчанию ученик проверяет ответ кнопкой. Режим общий для всех назначений листка.')
    restrict_clipboard = forms.BooleanField(label=RESTRICT_LABEL, required=False)
    swap_numbers = forms.BooleanField(label=SWAP_LABEL, required=False, help_text=SWAP_HELP)
    allow_photos = forms.BooleanField(
        label='Принимать фото решений', required=False, initial=True)

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        # Подборки-образцы не выдаются (их сначала берут как листок)
        self.fields['worksheet'].queryset = (
            Worksheet.assignable_to(teacher).select_related('owner')
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
                    'Режим уже выданного листка меняется в конструкторе: '
                    '«Редактировать назначения».')
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


class AssignmentSettingsForm(forms.Form):
    """Параметры существующих назначений; пустой выбор сохраняет различия."""
    YES_NO = ('allow_photos', 'restrict_clipboard', 'swap_numbers')

    check_visibility = forms.ChoiceField(
        label='Автосверка ответов — для всего листка', required=False,
        choices=[('', 'Не менять')] + Assignment.CHECK_CHOICES)
    restrict_clipboard = forms.ChoiceField(
        label='Копирование условий и вставка ответов', required=False,
        choices=[('', 'Не менять'), ('yes', 'Запретить'), ('no', 'Разрешить')])
    swap_numbers = forms.ChoiceField(
        label='Подмена чисел при копировании', required=False,
        choices=[('', 'Не менять'), ('yes', 'Подменять'), ('no', 'Не подменять')])
    allow_photos = forms.ChoiceField(
        label='Фото решений', required=False,
        choices=[('', 'Не менять'), ('yes', 'Принимать'), ('no', 'Не принимать')])
    due_action = forms.ChoiceField(
        label='Срок сдачи', choices=[('keep', 'Не менять'), ('set', 'Установить'), ('clear', 'Без срока')])
    due_at = forms.DateTimeField(
        label='Дата и время', required=False, input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))

    def __init__(self, *args, recipients, whole_worksheet=False, **kwargs):
        initial = {'due_action': 'keep'}
        for field in ('check_visibility', 'allow_photos', 'due_at', 'restrict_clipboard', 'swap_numbers'):
            values = {getattr(a, field) for a in recipients}
            if len(values) == 1:
                value = values.pop()
                initial[field] = ('yes' if value else 'no') if field in self.YES_NO else value
        super().__init__(*args, initial=initial, **kwargs)
        if not whole_worksheet:
            self.fields.pop('check_visibility')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('due_action') == 'set' and not cleaned.get('due_at'):
            self.add_error('due_at', 'Укажите дату и время.')
        return cleaned

    def changes(self):
        """Только явно выбранные изменения после успешной валидации."""
        data, changes = self.cleaned_data, {}
        if data.get('check_visibility'):
            changes['check_visibility'] = data['check_visibility']
        if data.get('allow_photos'):
            changes['allow_photos'] = data['allow_photos'] == 'yes'
        for field in self.YES_NO:
            if data.get(field):
                changes[field] = data[field] == 'yes'
        if data['due_action'] != 'keep':
            changes['due_at'] = data['due_at'] if data['due_action'] == 'set' else None
        return changes
