import secrets
from datetime import timedelta

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .models import (INVITE_DEFAULT_DAYS, Profile, StudentGroup,
                     TeacherInvite, default_teacher)

STUDENT_LINK_INVALID = ('Ссылка недействительна — попросите у учителя '
                        'новую ссылку для регистрации.')

REGISTRATION_USERNAME_MIN_LENGTH = 3
REGISTRATION_USERNAME_MAX_LENGTH = 30
REGISTRATION_NAME_MAX_LENGTH = 50
REGISTRATION_PASSWORD_MAX_LENGTH = 128

registration_username_validator = RegexValidator(
    regex=r'^[A-Za-z0-9._-]+\Z',
    message=(
        'Используйте только латинские буквы, цифры, точку, дефис '
        'и подчёркивание.'),
)
registration_name_validator = RegexValidator(
    regex=r"^[^\W\d_]+(?:[ '\-’][^\W\d_]+)*\Z",
    message='Используйте только буквы, пробел, дефис или апостроф.',
)

# Транслитерация для генерации логина из фамилии
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def translit(text):
    return ''.join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def generate_username(first_name, last_name, fallback='uchenik'):
    base = slugify(translit(f'{last_name}.{first_name}'))[:24] or fallback
    username = base
    n = 1
    while User.objects.filter(username=username).exists():
        n += 1
        username = f'{base}{n}'
    return username


def generate_password():
    """Короткий читаемый пароль без неоднозначных символов."""
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(8))


class RegistrationForm(forms.Form):
    """Общее для самостоятельной регистрации ученика и учителя по
    приглашению: имя, фамилия, логин, пароль дважды, их валидаторы."""

    first_name = forms.CharField(
        label='Имя', max_length=REGISTRATION_NAME_MAX_LENGTH,
        validators=[registration_name_validator],
        widget=forms.TextInput(attrs={
            'autocomplete': 'given-name',
            'autofocus': True,
            'data-name-field': '',
        }),
    )
    last_name = forms.CharField(
        label='Фамилия', max_length=REGISTRATION_NAME_MAX_LENGTH,
        validators=[registration_name_validator],
        widget=forms.TextInput(attrs={
            'autocomplete': 'family-name',
            'data-name-field': '',
        }),
    )
    username = forms.CharField(
        label='Логин', min_length=REGISTRATION_USERNAME_MIN_LENGTH,
        max_length=REGISTRATION_USERNAME_MAX_LENGTH,
        validators=[registration_username_validator],
        help_text=(
            '3–30 символов: латинские буквы, цифры, точка, дефис '
            'и подчёркивание.'),
        widget=forms.TextInput(attrs={
            'autocomplete': 'username',
            'autocapitalize': 'none',
            'spellcheck': 'false',
            # Дефис экранирован: браузеры компилируют pattern с флагом v,
            # где «-» в классе символов без экранирования — ошибка
            'pattern': r'[A-Za-z0-9._\-]{3,30}',
            'data-username-field': '',
        }),
    )
    password1 = forms.CharField(
        label='Пароль', max_length=REGISTRATION_PASSWORD_MAX_LENGTH,
        strip=False,
        help_text='От 6 до 128 символов. Можно использовать любые символы.',
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'new-password',
            'minlength': 6,
            'data-password-field': '',
        }),
    )
    password2 = forms.CharField(
        label='Повторите пароль',
        max_length=REGISTRATION_PASSWORD_MAX_LENGTH, strip=False,
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'new-password',
            'minlength': 6,
            'data-password-confirmation': '',
        }),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].lower()
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Этот логин уже занят.')
        return username

    def clean_password1(self):
        password = self.cleaned_data['password1']
        password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Пароли не совпадают.')
        return cleaned_data

    def create_user(self):
        return User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password1'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name'],
        )


class StudentRegistrationForm(RegistrationForm):
    """Самостоятельная регистрация ученика.

    ``teacher_code`` — код из персональной ссылки учителя
    (``?t=<Profile.student_code>``), переносится скрытым полем; без кода
    ученик записывается к ``default_teacher()``, как раньше.
    """

    teacher_code = forms.CharField(
        required=False, max_length=16, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = None

    def clean(self):
        cleaned_data = super().clean()
        code = cleaned_data.get('teacher_code', '').strip()
        if code:
            self.teacher = Profile.teacher_by_student_code(code)
            if self.teacher is None:
                raise forms.ValidationError(STUDENT_LINK_INVALID)
        return cleaned_data

    @transaction.atomic
    def save(self):
        user = self.create_user()
        Profile.objects.create(
            user=user, role=Profile.ROLE_STUDENT,
            teacher=self.teacher or default_teacher())
        return user


class InviteUnavailable(Exception):
    """Приглашение погашено или истекло между показом формы и отправкой."""


class TeacherJoinForm(RegistrationForm):
    """Регистрация учителя по приглашению.

    Логин можно не заполнять: составится из фамилии и имени транслитом
    (``generate_username``); то же подставляет на лету ``registration.js``.
    """

    email = forms.EmailField(
        label='Почта', required=False,
        help_text=('Необязательно. Пригодится, чтобы восстановить пароль и '
                   'получать уведомления, когда на сайте появится почта.'),
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )

    def __init__(self, *args, invite=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invite = invite
        self.fields['username'].required = False
        self.fields['username'].help_text = (
            '3–30 символов: латинские буквы, цифры, точка, дефис и '
            'подчёркивание. Если оставить пустым — составится из фамилии '
            'и имени.')
        if invite is not None and invite.email and not self.is_bound:
            self.fields['email'].initial = invite.email

    def clean(self):
        cleaned_data = super().clean()
        if (not cleaned_data.get('username') and 'username' not in self.errors
                and cleaned_data.get('first_name')
                and cleaned_data.get('last_name')):
            cleaned_data['username'] = generate_username(
                cleaned_data['first_name'], cleaned_data['last_name'],
                fallback='uchitel')
        return cleaned_data

    @transaction.atomic
    def save(self):
        """Погашает приглашение и создаёт учителя одной транзакцией:
        второй запрос с тем же токеном не пройдёт условный UPDATE, а
        ошибка создания пользователя откатит и погашение."""
        if not self.invite.claim():
            raise InviteUnavailable
        user = self.create_user()
        if self.cleaned_data.get('email'):
            user.email = self.cleaned_data['email']
            user.save(update_fields=['email'])
        Profile.objects.create(
            user=user, role=Profile.ROLE_TEACHER,
            invited_by=self.invite.created_by,
            base_editor=self.invite.base_editor)
        TeacherInvite.objects.filter(pk=self.invite.pk).update(used_by=user)
        self.invite.used_by = user
        return user


class TeacherInviteForm(forms.Form):
    """Выписать приглашение: заметка, срок в днях, право править базу."""

    note = forms.CharField(
        label='Кому', max_length=200, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Имя или школа — для списка'}))
    email = forms.EmailField(label='Почта', required=False)
    days = forms.IntegerField(
        label='Срок, дней', min_value=1, max_value=365,
        initial=INVITE_DEFAULT_DAYS)
    base_editor = forms.BooleanField(
        label='Может править общие задачи', required=False)

    def save(self, created_by):
        return TeacherInvite.objects.create(
            created_by=created_by,
            note=self.cleaned_data['note'].strip(),
            email=self.cleaned_data['email'],
            expires_at=timezone.now() + timedelta(days=self.cleaned_data['days']),
            base_editor=self.cleaned_data['base_editor'],
        )


class TeacherProfileForm(forms.Form):
    """Мини-профиль учителя: имя попадает в шапку PDF как автор листка."""

    first_name = forms.CharField(
        label='Имя', max_length=150,
        widget=forms.TextInput(attrs={'autocomplete': 'given-name'}))
    last_name = forms.CharField(
        label='Фамилия', max_length=150,
        widget=forms.TextInput(attrs={'autocomplete': 'family-name'}))
    email = forms.EmailField(
        label='Почта', required=False,
        help_text='Необязательно: для восстановления пароля и уведомлений, '
                  'когда на сайте появится почта.',
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}))

    def __init__(self, *args, user, **kwargs):
        kwargs.setdefault('initial', {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
        })
        super().__init__(*args, **kwargs)
        self.user = user

    def save(self):
        self.user.first_name = self.cleaned_data['first_name'].strip()
        self.user.last_name = self.cleaned_data['last_name'].strip()
        self.user.email = self.cleaned_data['email']
        self.user.save(update_fields=['first_name', 'last_name', 'email'])
        return self.user


class StudentCreateForm(forms.Form):
    first_name = forms.CharField(label='Имя', max_length=150)
    last_name = forms.CharField(label='Фамилия', max_length=150)
    grade = forms.IntegerField(
        label='Класс', min_value=1, max_value=11, required=False)

    def save(self, teacher):
        first_name = self.cleaned_data['first_name']
        last_name = self.cleaned_data['last_name']
        username = generate_username(first_name, last_name)
        password = generate_password()
        user = User.objects.create_user(
            username=username, password=password,
            first_name=first_name, last_name=last_name)
        Profile.objects.create(
            user=user, role=Profile.ROLE_STUDENT,
            grade=self.cleaned_data.get('grade'), teacher=teacher)
        return user, password


class StudentEditForm(forms.Form):
    """Правка данных ученика: имя, фамилия, класс, группы."""
    first_name = forms.CharField(label='Имя', max_length=150)
    last_name = forms.CharField(label='Фамилия', max_length=150)
    grade = forms.IntegerField(
        label='Класс', min_value=1, max_value=11, required=False)
    groups = forms.ModelMultipleChoiceField(
        label='Группы', required=False,
        queryset=StudentGroup.objects.none(),
        widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        if teacher is not None:
            self.fields['groups'].queryset = (
                StudentGroup.visible_to(teacher).select_related('teacher'))
            if teacher.is_superuser:
                self.fields['groups'].label_from_instance = lambda group: (
                    f'{group.name} — '
                    f'{group.teacher.get_full_name() or group.teacher.username}')

    def save(self, profile):
        user = profile.user
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.save()
        profile.grade = self.cleaned_data.get('grade')
        profile.save()
        selected = set(self.cleaned_data['groups'])
        for group in self.fields['groups'].queryset:
            if group in selected:
                group.students.add(user)
            else:
                group.students.remove(user)
        return user


class StudentGroupForm(forms.ModelForm):
    teacher = forms.ModelChoiceField(
        label='Владелец', required=False, queryset=User.objects.none())

    class Meta:
        model = StudentGroup
        fields = ['name']

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = teacher
        if teacher and teacher.is_superuser:
            self.fields['teacher'].queryset = (User.objects.filter(
                Q(profile__role=Profile.ROLE_TEACHER) | Q(is_superuser=True))
                .distinct().order_by('last_name', 'first_name', 'username'))
            if self.instance.pk:
                self.fields['teacher'].initial = self.instance.teacher
            else:
                self.fields['teacher'].required = True
                self.fields['teacher'].initial = teacher

    def _owner(self):
        if self.instance.pk:
            return self.instance.teacher
        if self.actor and self.actor.is_superuser:
            return self.cleaned_data.get('teacher')
        return self.actor

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('name')
        owner = self._owner()
        if name and owner:
            qs = StudentGroup.objects.filter(teacher=owner, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('name', 'Группа с таким названием уже есть.')
        return cleaned

    def save(self, commit=True):
        group = super().save(commit=False)
        if not group.pk:
            group.teacher = self._owner()
        if commit:
            group.save()
        return group
