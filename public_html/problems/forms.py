from django import forms
from django.forms import inlineformset_factory

from .models import Task, TaskImage, TaskSource, TaskSubitem


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['text_latex', 'columns',
                  'answer_latex', 'solution_latex',
                  'grade_level', 'stars', 'difficulty', 'answer_type']
        widgets = {
            'text_latex': forms.Textarea(attrs={'rows': 5}),
            'answer_latex': forms.Textarea(attrs={'rows': 2}),
            'solution_latex': forms.Textarea(attrs={'rows': 4}),
            'grade_level': forms.HiddenInput(),
        }


TaskSourceFormSet = inlineformset_factory(
    Task, TaskSource,
    fields=['source', 'number'],
    extra=1, can_delete=True,
)


TaskSubitemFormSet = inlineformset_factory(
    Task, TaskSubitem,
    fields=['order', 'text_latex', 'answer_latex', 'solution_latex'],
    widgets={
        'text_latex': forms.Textarea(attrs={'rows': 2}),
        'answer_latex': forms.Textarea(attrs={'rows': 1}),
        'solution_latex': forms.Textarea(attrs={'rows': 1}),
    },
    extra=1, can_delete=True,
)


TaskImageFormSet = inlineformset_factory(
    Task, TaskImage,
    fields=['order', 'image'],
    widgets={
        'image': forms.ClearableFileInput(
            attrs={'accept': '.png,.jpg,.jpeg,.pdf,image/*'}),
    },
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
