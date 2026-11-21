from django import forms

from .filenames import clean_prefix
from .models import Worksheet


class WorksheetForm(forms.ModelForm):
    """«Свойства листка»: шапка редактируется прямо в макете шапки PDF
    (worksheet_form.html, static/js/worksheet_form.js)."""

    class Meta:
        model = Worksheet
        fields = ['title', 'grade_label', 'subtitle', 'author_name',
                  'pdf_prefix', 'pdf_basename', 'comment']
        widgets = {
            'comment': forms.Textarea(attrs={'rows': 3}),
        }

    # Поля шапки — поля ввода внутри макета: подписи вместо label
    HEAD_PLACEHOLDERS = {
        'title': 'Название листка',
        'grade_label': 'Слева: например, 8 класс',
        'subtitle': 'Подзаголовок, если нужен',
    }

    def __init__(self, *args, author_placeholder='', **kwargs):
        super().__init__(*args, **kwargs)
        for name, text in self.HEAD_PLACEHOLDERS.items():
            self.fields[name].widget.attrs.update(
                {'placeholder': text, 'class': 'sheet-head-input', 'autocomplete': 'off'})
        self.fields['author_name'].widget.attrs.update({
            'placeholder': author_placeholder or 'Справа: например, ФИО',
            'class': 'sheet-head-input', 'autocomplete': 'off'})
        for name in (*self.HEAD_PLACEHOLDERS, 'author_name'):
            self.fields[name].widget.attrs['aria-label'] = self.fields[name].label
        self.fields['pdf_prefix'].widget.attrs.update(
            {'placeholder': 'предмет и класс', 'autocomplete': 'off', 'spellcheck': 'false'})

    def clean_pdf_prefix(self):
        raw = self.cleaned_data.get('pdf_prefix', '')
        prefix = clean_prefix(raw)
        if raw.strip() and not prefix:
            raise forms.ValidationError(
                'В префиксе нужны буквы или цифры: например, lyceum8.')
        return prefix
