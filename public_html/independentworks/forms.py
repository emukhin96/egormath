from django import forms
from accounts.models import Profile, StudentGroup
from .models import Work
from assignments.forms import StudentChoiceField


class WorkForm(forms.ModelForm):
    class Meta:
        model = Work
        fields = ['title']


class RunForm(forms.Form):
    students = StudentChoiceField(label='Отдельные ученики', queryset=Profile.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    groups = forms.ModelMultipleChoiceField(label='Группы', queryset=StudentGroup.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    duration = forms.IntegerField(label='Длительность, минут', min_value=1, max_value=1440, initial=40)
    deadline = forms.DateTimeField(label='Общее окончание (необязательно)', required=False, input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    max_variants = forms.IntegerField(label='Максимально вариантов', required=False, min_value=1)
    restrict_clipboard = forms.BooleanField(
        label='Ограничить копирование условий и вставку ответов',
        required=False, initial=True)
    allow_photos = forms.BooleanField(
        label='Принимать фотографии', required=False, initial=False)
    withhold_answers = forms.BooleanField(label='Не показывать ответы сразу', required=False, initial=True, widget=forms.CheckboxInput(attrs={'role': 'switch'}))
    release_mode = forms.ChoiceField(label='Публикация', choices=[('manual', 'После одобрения учителя'), ('auto', 'Сразу после сдачи')])
    release_flags = forms.MultipleChoiceField(label='Что показывать после сдачи', required=False, choices=[('checks', 'Правильность и итог'), ('answer', 'Правильный ответ'), ('solution', 'Решение'), ('comment', 'Комментарий')], widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, teacher, **kwargs):
        if args and args[0] is not None and 'release_toggle' in args[0]:
            data = args[0].copy()
            data['release_mode'] = 'manual' if data.get('withhold_answers') else 'auto'
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.initial['withhold_answers'] = self.initial.get('release_mode', 'manual') == 'manual'
        self.fields['students'].queryset = Profile.student_users_for(teacher).select_related('profile').order_by('last_name', 'first_name', 'username')
        self.fields['groups'].queryset = StudentGroup.visible_to(teacher)

    def recipients(self, teacher):
        selected = set(self.cleaned_data['students'].values_list('pk', flat=True))
        selected.update(Profile.student_users_for(teacher).filter(member_groups__in=self.cleaned_data['groups']).values_list('pk', flat=True))
        return selected
