"""Каркас страниц после ревизии интерфейса 03.11.2026 (артефакт «Ревизия
интерфейса», замечания G1–G4, G9, G11).

- G4: в видимом тексте шаблонов, JS и CSS нет разделителя «·» — фразы через
  запятую. Строки действий («PDF · Дублировать …») пока исключение: их
  счётчик по файлу зафиксирован в ``DOT_ALLOWED`` и должен только убывать.
- G9: раздел верхнего меню считает ``accounts.context_processors.nav_section``
  по приложению, а не по подстроке имени URL.
- G1, G2: боковая панель — только у списков с фильтрами и у редакторов с
  настройками; экраны-формы и экраны с одной подсказкой — без неё.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import resolve, reverse

from accounts.context_processors import nav_section
from accounts.models import Profile

DOT = '·'

# Файл → сколько «·» в нём ещё допустимо. Только строки действий (решение
# Егора по G4: «Действия оставим пока как исключение») и знак умножения в
# разборе формул. Убрали действие в меню «⋯» — уменьшите число.
DOT_ALLOWED = {
    'templates/worksheets/worksheet_detail.html': 2,  # действия ссылки доступа
    'static/js/problem_masks.js': 1,                # ссылки масок подпунктов
    'static/js/numberline.js': 1,                   # \cdot → умножение
    'static/js/quick_clone.js': 1,                  # \cdot → умножение
}

TEMPLATE_COMMENTS = re.compile(r'{#.*?#}|{%\s*comment\s*%}.*?{%\s*endcomment\s*%}', re.DOTALL)
JS_COMMENTS = re.compile(r'/\*.*?\*/|(?<![:\'"])//[^\n]*', re.DOTALL)
CSS_COMMENTS = re.compile(r'/\*.*?\*/', re.DOTALL)


def visible_dots(base):
    """Файл → число «·» вне комментариев (в CSS — только в ``content:``)."""
    found = {}
    sets = (
        ('templates', '*.html', TEMPLATE_COMMENTS),
        ('static/js', '*.js', JS_COMMENTS),
        ('static/css', '*.css', CSS_COMMENTS),
    )
    for folder, pattern, comments in sets:
        for path in sorted((base / folder).rglob(pattern)):
            name = str(path.relative_to(base))
            if name.endswith(('app.css', '_screens.css')):
                continue  # сборки: проверяются исходники
            text = comments.sub('', path.read_text(encoding='utf-8'))
            if folder == 'static/css':
                count = sum(line.count(DOT) for line in text.splitlines() if 'content' in line or '--sep' in line)
            else:
                count = text.count(DOT)
            if count:
                found[name] = count
    return found


class DotSeparatorTests(SimpleTestCase):
    def test_no_new_dot_separators(self):
        found = visible_dots(Path(settings.BASE_DIR))
        extra = {name: count for name, count in found.items()
                 if count > DOT_ALLOWED.get(name, 0)}
        self.assertEqual(extra, {}, 'Разделитель «·» в видимом тексте: замените запятой '
                                    '(строки действий — см. DOT_ALLOWED)')

    def test_allowed_list_is_not_stale(self):
        """Исключение, которое уже не нужно, убирают из списка, чтобы «·» не вернулся."""
        found = visible_dots(Path(settings.BASE_DIR))
        stale = {name: (allowed, found.get(name, 0)) for name, allowed in DOT_ALLOWED.items()
                 if found.get(name, 0) < allowed}
        self.assertEqual(stale, {})


class NavSectionTests(SimpleTestCase):
    """G9: прогресс, доски и проверка — «Задания»; сверка импорта — «Задачи»."""

    def section(self, url):
        request = RequestFactory().get(url)
        request.resolver_match = resolve(url.split('?')[0])
        return nav_section(request)

    def test_sections(self):
        cases = {
            reverse('worksheet_progress', args=[1]): 'assignments',
            reverse('worksheet_boards', args=[1]): 'assignments',
            reverse('review_assignment', args=[1]): 'assignments',
            reverse('assignment_journal'): 'assignments',
            reverse('independentworks:catalog'): 'assignments',
            reverse('textbook_import_review', args=[1, 1]): 'tasks',
            reverse('task_list'): 'tasks',
            reverse('proposal_list'): 'tasks',
            reverse('worksheet_list'): 'worksheets',
            reverse('worksheet_detail', args=[1]): 'worksheets',
            reverse('collection_list'): 'collections',
            reverse('students'): 'students',
            reverse('teachers'): 'students',
            reverse('progress_overview'): 'students',
            reverse('dashboard'): '',
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(self.section(url), expected)

    def test_independent_mode_of_assignment_create(self):
        self.assertEqual(self.section(reverse('assignment_create') + '?mode=independent'), 'assignments')


class PanelTests(TestCase):
    """G1, G2: на формах и экранах-подсказках панели нет, у списков — есть."""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_superuser('frame_teacher', 'frame@example.com', 'pw')
        Profile.objects.get_or_create(user=cls.teacher, defaults={'role': Profile.ROLE_TEACHER})

    def setUp(self):
        self.client.force_login(self.teacher)

    def test_hint_panels_are_gone(self):
        for name in ('profile', 'bulk_answers', 'proposal_list', 'proposals_mine',
                     'teachers', 'task_create', 'worksheet_import', 'help_teachers'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'class="sidebar-section"')

    def test_list_panels_stay(self):
        for name in ('task_list', 'worksheet_list'):
            with self.subTest(name=name):
                self.assertContains(self.client.get(reverse(name)), 'class="sidebar-section"')

    def test_progress_highlights_assignments(self):
        from worksheets.models import Worksheet
        worksheet = Worksheet.objects.create(title='Листок каркаса', owner=self.teacher)
        response = self.client.get(reverse('worksheet_progress', args=[worksheet.pk]))
        self.assertEqual(response.context['nav_section'], 'assignments')
        self.assertContains(response, 'class="page-crumbs"')
        self.assertNotContains(response, 'live-back')


class TemplateCommentTests(SimpleTestCase):
    """{# … #} в Django однострочный: многострочный попадает на страницу
    текстом (так случилось с блоком «Показать»). Длинный — {% comment %}."""

    def test_no_multiline_short_comments(self):
        base = Path(settings.BASE_DIR) / 'templates'
        found = []
        for path in sorted(base.rglob('*.html')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                tail = line[line.rfind('{#'):] if '{#' in line else ''
                if tail and '#}' not in tail:
                    found.append(f'{path.relative_to(base)}:{number}')
        self.assertEqual(found, [])
