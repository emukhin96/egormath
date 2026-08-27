from django import forms
from django.forms import inlineformset_factory

from .models import (Task, TaskImage, TaskSource, TaskSubitem,
                     TextbookTaskDraft)


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


class TextbookBundleUploadForm(forms.Form):
    title = forms.CharField(label='Название партии', max_length=190)
    source_title = forms.CharField(label='Название задачника', max_length=190)
    source_author = forms.CharField(
        label='Автор(ы)', max_length=190, required=False)
    source_year = forms.IntegerField(
        label='Год издания', required=False, min_value=1000, max_value=9999)
    bundle = forms.FileField(
        label='import.json', help_text='Результат tools/textbook_parser.py')


class TextbookDraftReviewForm(forms.ModelForm):
    text_latex = forms.CharField(
        label='Условие (LaTeX)', required=False,
        widget=forms.Textarea(attrs={'rows': 8}))
    copy_solution_from = forms.CharField(
        label='Взять решение у ключа', max_length=190, required=False,
        help_text='Оставьте пустым, чтобы править текущий текст вручную')

    class Meta:
        model = TextbookTaskDraft
        fields = [
            'external_id', 'source_number', 'text_latex',
            'subitems', 'author_answer_latex', 'author_solution_latex', 'topic',
            'status',
        ]
        widgets = {
            'subitems': forms.Textarea(attrs={'rows': 8}),
            'author_answer_latex': forms.Textarea(attrs={'rows': 3}),
            'author_solution_latex': forms.Textarea(attrs={'rows': 12}),
        }

    def clean_subitems(self):
        from .textbook_import import TextbookImportError, normalize_subitems
        try:
            return normalize_subitems(self.cleaned_data['subitems'])
        except TextbookImportError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_external_id(self):
        external_id = self.cleaned_data['external_id'].strip()
        if (self.instance.batch_id
                and TextbookTaskDraft.objects.filter(
                    batch_id=self.instance.batch_id,
                    external_id=external_id).exclude(pk=self.instance.pk)
                .exists()):
            raise forms.ValidationError(
                'Такой ключ уже существует в этой партии.')
        return external_id

    def clean(self):
        cleaned = super().clean()
        if (not str(cleaned.get('text_latex') or '').strip()
                and not cleaned.get('subitems')):
            self.add_error(
                'text_latex',
                'Укажите общее условие или хотя бы один подпункт.')
        return cleaned
