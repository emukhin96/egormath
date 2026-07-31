import secrets

from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify

from .models import Profile

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


def generate_username(first_name, last_name):
    base = slugify(translit(f'{last_name}.{first_name}'))[:24] or 'uchenik'
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
