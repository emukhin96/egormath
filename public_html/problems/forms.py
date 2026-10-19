import os

from django import forms
from django.core.validators import FileExtensionValidator
from django.forms import inlineformset_factory

from .models import (Task, TaskImage, TaskSource, TaskSubitem,
                     TextbookTaskDraft)


def clean_mask_text(text):
    """Маска сохраняется только рабочей: ошибки грамматики и эталонов
    учитель видит сразу в форме, а не ученик на задании. Длина — в пределах
    MASK_MAX_LENGTH, иначе сохранённую маску нельзя было бы показать в превью
    и проверить «как ученик» (problems.views._mask_request)."""
    from assignments.checks import MASK_MAX_LENGTH, parse_mask
    text = (text or '').strip()
    if not text:
        return ''
    if len(text) > MASK_MAX_LENGTH:
        raise forms.ValidationError(f'Маска длиннее {MASK_MAX_LENGTH} символов')
    spec = parse_mask(text, validate_references=True)
    if spec.errors:
        raise forms.ValidationError(spec.errors)
    return text


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['text_latex', 'columns',
                  'answer_latex', 'solution_latex',
                  'author_answer_latex', 'author_solution_latex',
                  'grade_level', 'stars', 'difficulty', 'full_answer_only',
                  'answer_mask']
        widgets = {
            'text_latex': forms.Textarea(attrs={'rows': 5}),
            'answer_latex': forms.Textarea(attrs={'rows': 2}),
            'author_answer_latex': forms.Textarea(attrs={'rows': 2}),
            'author_solution_latex': forms.Textarea(attrs={'rows': 4}),
            'solution_latex': forms.Textarea(attrs={'rows': 4}),
            'grade_level': forms.HiddenInput(),
            'answer_mask': forms.Textarea(attrs={
                'rows': 2, 'data-mask-source': 'task',
                'placeholder': 'Например: Меньшая сторона равна {{number: 10}} см'}),
        }

    def clean_answer_mask(self):
        return clean_mask_text(self.cleaned_data.get('answer_mask'))


class TaskSubitemForm(forms.ModelForm):
    class Meta:
        model = TaskSubitem
        fields = ['order', 'text_latex', 'answer_latex', 'solution_latex',
                  'author_answer_latex', 'author_solution_latex',
                  'answer_mask']
        widgets = {
            'text_latex': forms.Textarea(attrs={'rows': 2}),
            'answer_latex': forms.Textarea(attrs={'rows': 1}),
            'author_answer_latex': forms.Textarea(attrs={'rows': 2}),
            'author_solution_latex': forms.Textarea(attrs={'rows': 4}),
            'solution_latex': forms.Textarea(attrs={'rows': 1}),
            'answer_mask': forms.Textarea(attrs={
                'rows': 1, 'data-mask-source': 'subitem',
                'placeholder': '{{number: …}}'}),
        }

    def clean_answer_mask(self):
        return clean_mask_text(self.cleaned_data.get('answer_mask'))


TaskSourceFormSet = inlineformset_factory(
    Task, TaskSource,
    fields=['source', 'number'],
    extra=1, can_delete=True,
)


TaskSubitemFormSet = inlineformset_factory(
    Task, TaskSubitem, form=TaskSubitemForm,
    extra=1, can_delete=True,
)


class TaskImageForm(forms.ModelForm):
    """Строка формсета картинок задачи.

    Картинка может прийти из буфера обмена (static/js/image_paste.js):
    имя тогда вида paste-20261014-153000.png, а при ручной сборке запроса —
    вовсе без расширения. Поэтому тип определяем по содержимому, а
    расширение имени приводим к нему: валидатор модели и сжатие в
    TaskImage.save() смотрят именно на имя. Нечитаемый или слишком большой
    файл — ошибка строки формы, а не 500 при сохранении.
    """

    class Meta:
        model = TaskImage
        fields = ['order', 'image']
        widgets = {
            # Миниатюру показывает сама строка (.pic-preview), поэтому
            # зона вставки из буфера — без своей картинки.
            'image': forms.ClearableFileInput(attrs={
                'accept': '.png,.jpg,.jpeg,.pdf,image/*',
                'data-image-paste-thumb': 'off'}),
        }

    def clean_image(self):
        from django.conf import settings
        from django.core.files.uploadedfile import UploadedFile
        from PIL import Image

        upload = self.cleaned_data.get('image')
        if not isinstance(upload, UploadedFile):
            return upload  # файл не меняли или отметили «очистить»
        limit = settings.TASK_IMAGE_MAX_SIZE_MB
        if upload.size > limit * 1024 * 1024:
            raise forms.ValidationError(
                f'Файл больше {limit} МБ — уменьшите картинку.')
        base = os.path.splitext(os.path.basename(upload.name or ''))[0]
        base = base or 'image'
        upload.seek(0)
        head = upload.read(5)
        upload.seek(0)
        if head.startswith(b'%PDF'):
            ext = '.pdf'
        else:
            try:
                with Image.open(upload) as img:
                    fmt = img.format
                    img.load()
            except Exception:
                raise forms.ValidationError(
                    'Файл не похож на картинку PNG/JPEG или PDF.')
            finally:
                upload.seek(0)
            # Не-PNG растр TaskImage._compress всё равно сохранит JPEG-ом
            ext = '.png' if fmt == 'PNG' else '.jpg'
        current = os.path.splitext(upload.name or '')[1].lower()
        if not (current == ext or (ext == '.jpg' and current == '.jpeg')):
            upload.name = base + ext
        return upload


TaskImageFormSet = inlineformset_factory(
    Task, TaskImage, form=TaskImageForm,
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
    INPUT_JSON = 'json'
    INPUT_ANSWERS_END = 'answers_end'
    INPUT_SEPARATE_SOLUTIONS = 'separate_solutions'
    INPUT_CHOICES = [
        (INPUT_JSON, 'Готовый import.json'),
        (INPUT_ANSWERS_END,
         'Один TEX: задачи и авторские ответы в конце'),
        (INPUT_SEPARATE_SOLUTIONS,
         'Два TEX: задачник и отдельная книга решений'),
    ]
    PROFILE_CHOICES = [
        ('', 'По компоновке: Галицкий / Шестаков'),
        ('galitsky', 'Галицкий: глобальные номера, ответы в конце'),
        ('merzlyak',
         'Мерзляк: номера «§.N», рисунки по подписям, ответы в конце'),
        ('shabunin',
         'Шабунин: номера «IV.12», ответы после каждой главы'),
        ('potoskuev',
         'Потоскуев: геометрия 10, номера «1.001», рисунки по подписям'),
        ('vysotsky',
         'Высоцкий: теория вероятностей 8–9, номера 1–396, карточки, СР и КР'),
        ('tkachuk',
         'Ткачук: «Математика — абитуриенту», уроки и варианты МГУ 1970–2021'),
        ('koropets',
         'Коропец: неравенства, примеры «П2.5» с разборами и самостоятельные'),
        ('feoktistov', 'Феоктистов: самостоятельные, контрольные, тесты'),
        ('ziv', 'Зив: работа / тема / вариант / номер'),
        ('shestakov', 'Шестаков: задачник и отдельный решебник'),
        ('ostromogilsky',
         'Остромогильский / ФИПИ ОГЭ: готовый import.json'),
        ('ostromogilsky_ege',
         'Остромогильский / ФИПИ ЕГЭ: готовый import.json'),
    ]

    title = forms.CharField(label='Название партии', max_length=190)
    source_title = forms.CharField(label='Название задачника', max_length=190)
    source_author = forms.CharField(
        label='Автор(ы)', max_length=190, required=False)
    source_year = forms.IntegerField(
        label='Год издания', required=False, min_value=1000, max_value=9999)
    input_kind = forms.ChoiceField(
        label='Компоновка исходных файлов', choices=INPUT_CHOICES,
        initial=INPUT_JSON, widget=forms.RadioSelect)
    profile = forms.ChoiceField(
        label='Профиль парсера', choices=PROFILE_CHOICES, required=False,
        help_text='Если оставить «По компоновке», один TEX разбирается как '
                  'Галицкий, два TEX — как Шестаков.')
    bundle = forms.FileField(
        label='Готовый import.json', required=False,
        validators=[FileExtensionValidator(['json'])],
        help_text='Используйте, если JSON уже сформирован CLI-парсером.')
    tasks_tex = forms.FileField(
        label='TEX с текстами задач', required=False,
        validators=[FileExtensionValidator(['tex'])],
        help_text='Для одного TEX этот же файл должен содержать '
                  'раздел авторских ответов в конце.')
    solutions_tex = forms.FileField(
        label='TEX с авторскими решениями', required=False,
        validators=[FileExtensionValidator(['tex'])],
        help_text='Нужен только при выборе отдельной книги решений.')
    images_zip = forms.FileField(
        label='ZIP с рисунками', required=False,
        validators=[FileExtensionValidator(['zip'])],
        help_text='Необязательно. Имена файлов должны совпадать со '
                  'ссылками \\includegraphics / \\taskpic.')

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get('input_kind')
        profile = (cleaned.get('profile') or '').strip()
        if kind == self.INPUT_JSON and not cleaned.get('bundle'):
            self.add_error('bundle', 'Выберите файл import.json.')
        if kind in {self.INPUT_ANSWERS_END,
                    self.INPUT_SEPARATE_SOLUTIONS}:
            if not cleaned.get('tasks_tex'):
                self.add_error('tasks_tex', 'Выберите TEX с задачами.')
        if (kind == self.INPUT_SEPARATE_SOLUTIONS
                and not cleaned.get('solutions_tex')):
            self.add_error(
                'solutions_tex', 'Выберите TEX с авторскими решениями.')
        if profile == 'shestakov' and kind == self.INPUT_ANSWERS_END:
            self.add_error(
                'profile',
                'Профиль Шестакова требует отдельный TEX с решениями.')
        if profile in {'ostromogilsky', 'ostromogilsky_ege'} and kind != self.INPUT_JSON:
            self.add_error(
                'profile',
                'Банк ФИПИ загружается готовым import.json: сначала CLI '
                'с --answers-pdf, затем этот файл.')
        cleaned['resolved_profile'] = (
            profile or (
                'shestakov' if kind == self.INPUT_SEPARATE_SOLUTIONS
                else 'galitsky'))
        return cleaned


class TextbookImageArchiveForm(forms.Form):
    images_zip = forms.FileField(
        label='ZIP с рисунками',
        validators=[FileExtensionValidator(['zip'])],
        help_text='Сопоставление идёт по имени файла без расширения.')


class TextbookDraftReviewForm(forms.ModelForm):
    text_latex = forms.CharField(
        label='Условие (LaTeX)', required=False,
        widget=forms.Textarea(attrs={'rows': 8}))
    # Метки сайта (как «Теги» в редакторе задачи): через запятую; при
    # загрузке в каталог создаются и привязываются к задаче.
    tags = forms.CharField(
        label='Метки', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Через запятую'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Метку с запятой в имени через это поле не выразить — её не
        # показываем и сохраняем как есть (как теги в редакторе задачи).
        self.initial['tags'] = ', '.join(
            name for name in self.instance.tags or [] if ',' not in name)
        if self.instance.pk and (
                self.instance.status == TextbookTaskDraft.STATUS_IMPORTED):
            for field in self.fields.values():
                field.disabled = True
            return
        self.fields['status'].choices = [
            choice for choice in TextbookTaskDraft.STATUS_CHOICES
            if choice[0] != TextbookTaskDraft.STATUS_IMPORTED]

    class Meta:
        model = TextbookTaskDraft
        fields = [
            'external_id', 'source_number', 'text_latex',
            'subitems', 'author_answer_latex', 'answer_mask',
            'author_solution_latex', 'answer_latex', 'solution_latex',
            'tags', 'status',
        ]
        widgets = {
            'subitems': forms.Textarea(attrs={'rows': 8}),
            'answer_latex': forms.Textarea(attrs={'rows': 3}),
            'solution_latex': forms.Textarea(attrs={'rows': 12}),
            'author_answer_latex': forms.Textarea(attrs={'rows': 3}),
            'answer_mask': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Например: {{number: 10}} см',
            }),
            'author_solution_latex': forms.Textarea(attrs={'rows': 12}),
        }

    def clean_tags(self):
        names = []
        for name in (self.cleaned_data.get('tags') or '').split(','):
            name = ' '.join(name.split())[:64]
            if name and name not in names:
                names.append(name)
        return names + [name for name in self.instance.tags or []
                        if ',' in name and name not in names]

    def clean_text_latex(self):
        from .textbook_parser import apply_imported_math, collapse_repeated_lead
        return collapse_repeated_lead(apply_imported_math(
            self.cleaned_data.get('text_latex') or ''))

    def clean_author_answer_latex(self):
        from .textbook_parser import apply_imported_answer
        return apply_imported_answer(
            self.cleaned_data.get('author_answer_latex') or '')

    def clean_answer_mask(self):
        return clean_mask_text(self.cleaned_data.get('answer_mask'))

    def clean_author_solution_latex(self):
        from .textbook_parser import apply_imported_math
        return apply_imported_math(
            self.cleaned_data.get('author_solution_latex') or '')

    def clean_answer_latex(self):
        from .textbook_parser import apply_imported_answer
        return apply_imported_answer(self.cleaned_data.get('answer_latex') or '')

    def clean_solution_latex(self):
        from .textbook_parser import apply_imported_math
        return apply_imported_math(self.cleaned_data.get('solution_latex') or '')

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
