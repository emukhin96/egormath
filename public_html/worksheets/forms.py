from django import forms

from .models import Worksheet


class WorksheetForm(forms.ModelForm):
    class Meta:
        model = Worksheet
        fields = ['title', 'grade_label', 'subtitle', 'author_name',
                  'pdf_basename', 'comment']
        widgets = {
            'comment': forms.Textarea(attrs={'rows': 3}),
        }
