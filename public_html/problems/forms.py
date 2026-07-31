from django import forms
from django.forms import inlineformset_factory

from .models import Task, TaskSource


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['text_latex', 'subitems_latex', 'columns',
                  'answer_latex', 'solution_latex',
                  'grade_level', 'stars', 'answer_type', 'topics', 'tags']
        widgets = {
            'text_latex': forms.Textarea(attrs={'rows': 5}),
            'subitems_latex': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': '\\item первый подпункт;\n\\item второй подпункт.'}),
            'answer_latex': forms.Textarea(attrs={'rows': 2}),
            'solution_latex': forms.Textarea(attrs={'rows': 4}),
            'topics': forms.SelectMultiple(attrs={'size': 10}),
            'tags': forms.CheckboxSelectMultiple(),
        }


TaskSourceFormSet = inlineformset_factory(
    Task, TaskSource,
    fields=['source', 'number'],
    extra=1, can_delete=True,
)


class TaskFilterForm(forms.Form):
    """Фильтры каталога задач (все поля необязательны)."""
    q = forms.CharField(label='Поиск', required=False)
    topic = forms.IntegerField(required=False, widget=forms.HiddenInput)
    grade = forms.TypedChoiceField(
        label='Класс', required=False, coerce=int,
        choices=[('', 'Любой')] + Task.GRADE_CHOICES)
    tag = forms.CharField(required=False)
