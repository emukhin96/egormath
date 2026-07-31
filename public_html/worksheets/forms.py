from django import forms

from .models import Worksheet


class WorksheetForm(forms.ModelForm):
    class Meta:
        model = Worksheet
        fields = ['title', 'grade_label', 'subtitle', 'author_name']
