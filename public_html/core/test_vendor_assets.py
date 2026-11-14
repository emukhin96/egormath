"""Inter, KaTeX, Sortable, MathLive и modern-screenshot раздаются со своего
сервера (static/vendor): в шаблонах и скриптах нет ссылок на Google Fonts и
jsdelivr, а все файлы, на которые ссылаются их CSS, есть в статике (аудит
быстродействия 06.11.2026, пункт 5; MathLive — третий круг, пункт 6)."""
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.templatetags.static import static
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.functional import empty

from problems.tests import make_teacher

TEMPLATES_DIR = Path(settings.BASE_DIR) / 'templates'
JS_DIR = Path(settings.BASE_DIR) / 'static' / 'js'
CSS_INPUT = Path(settings.BASE_DIR) / 'static' / 'css' / 'input.css'
FORBIDDEN = ('fonts.googleapis.com', 'fonts.gstatic.com',
             'cdn.jsdelivr.net/npm/katex', 'cdn.jsdelivr.net/npm/sortablejs',
             'cdn.jsdelivr.net/npm/mathlive', 'cdn.jsdelivr.net/npm/modern-screenshot')
# Семейства, которые MathLive ждёт готовыми при --ML__static-fonts (loadFonts
# в mathlive.min.js); все они объявлены в katex.min.css, шрифты те же
MATHLIVE_FAMILIES = ('KaTeX_Main', 'KaTeX_Math', 'KaTeX_AMS', 'KaTeX_Caligraphic',
                     'KaTeX_Fraktur', 'KaTeX_SansSerif', 'KaTeX_Script', 'KaTeX_Typewriter',
                     'KaTeX_Size1', 'KaTeX_Size2', 'KaTeX_Size3', 'KaTeX_Size4')
MATHLIVE_SOUNDS = ('keypress-delete', 'keypress-return', 'keypress-spacebar',
                   'keypress-standard', 'plonk')


class VendorTemplatesTests(SimpleTestCase):
    def test_templates_do_not_reference_moved_cdns(self):
        offenders = []
        for path in TEMPLATES_DIR.rglob('*.html'):
            text = path.read_text(encoding='utf-8')
            for host in FORBIDDEN:
                if host in text:
                    offenders.append((path.relative_to(TEMPLATES_DIR), host))
        self.assertEqual(offenders, [])

    def test_scripts_do_not_reference_moved_cdns(self):
        """modern-screenshot грузился из task_png.js адресом jsdelivr."""
        offenders = []
        for path in JS_DIR.glob('*.js'):
            if path.name == 'app.js':
                continue
            text = path.read_text(encoding='utf-8')
            for host in FORBIDDEN + ('cdn.jsdelivr.net', 'unpkg.com'):
                if host in text:
                    offenders.append((path.name, host))
        self.assertEqual(offenders, [])

    def test_mathlive_files_and_fonts(self):
        for name in ('vendor/mathlive/mathlive.min.js', 'vendor/mathlive/LICENSE',
                     'vendor/modern-screenshot/modern-screenshot.js',
                     'vendor/modern-screenshot/LICENSE'):
            self.assertIsNotNone(finders.find(name), name)
        for sound in MATHLIVE_SOUNDS:
            self.assertIsNotNone(finders.find(f'vendor/mathlive/sounds/{sound}.wav'), sound)
        # Шрифты MathLive не дублируем: --ML__static-fonts и @font-face KaTeX
        self.assertIsNone(finders.find('vendor/mathlive/fonts'))
        self.assertIn('--ML__static-fonts: true', CSS_INPUT.read_text(encoding='utf-8'))
        katex_css = Path(finders.find('vendor/katex/katex.min.css')).read_text(encoding='utf-8')
        families = set(re.findall(r'@font-face\{[^}]*font-family:"?(KaTeX_\w+)"?', katex_css))
        self.assertEqual(set(MATHLIVE_FAMILIES) - families, set())
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        self.assertIn("{% static 'vendor/katex/katex.min.css' %}", base)
        self.assertIn("data-lib=\"{% static 'vendor/modern-screenshot/modern-screenshot.js' %}\"", base)

    def test_vendor_css_references_existing_files(self):
        for css_name in ('vendor/katex/katex.min.css', 'vendor/inter/inter.css'):
            css_path = finders.find(css_name)
            self.assertIsNotNone(css_path, css_name)
            folder = Path(css_name).parent
            urls = set(re.findall(r'url\(([^)]+)\)', Path(css_path).read_text(encoding='utf-8')))
            self.assertTrue(urls, css_name)
            for url in urls:
                url = url.strip('\'"')
                self.assertFalse(url.startswith(('http:', 'https:', '//')), url)
                self.assertIsNotNone(finders.find(str(folder / url)), f'{css_name}: нет {url}')
        for name in ('vendor/katex/katex.min.js', 'vendor/katex/contrib/auto-render.min.js',
                     'vendor/sortable/Sortable.min.js', 'vendor/katex/LICENSE',
                     'vendor/inter/LICENSE.txt', 'vendor/sortable/LICENSE'):
            self.assertIsNotNone(finders.find(name), name)

    def test_collectstatic_hashes_vendor_fonts(self):
        with tempfile.TemporaryDirectory() as root:
            storages = {
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'core.staticfiles.HashedStaticFilesStorage'},
            }
            with override_settings(STATIC_ROOT=root, STORAGES=storages):
                from django.contrib.staticfiles.storage import staticfiles_storage
                staticfiles_storage._wrapped = empty
                call_command('collectstatic', interactive=False, verbosity=0)
                css_url = static('vendor/katex/katex.min.css')
                self.assertRegex(css_url, r'^/static/vendor/katex/katex\.min\.[0-9a-f]{12}\.css$')
                hashed = Path(root) / css_url[len('/static/'):]
                text = hashed.read_text(encoding='utf-8')
                # Ссылки на шрифты внутри CSS тоже с хэшем: кэш на год безопасен
                self.assertRegex(text, r'url\("?fonts/KaTeX_Main-Regular\.[0-9a-f]{12}\.woff2"?\)')
                self.assertNotIn('KaTeX_Main-Regular.woff2)', text)
                # MathLive берёт звуки по ./sounds/ от адреса скрипта (без хэша):
                # исходные имена после collectstatic остаются рядом с хэшированными
                js_url = static('vendor/mathlive/mathlive.min.js')
                self.assertRegex(js_url, r'^/static/vendor/mathlive/mathlive\.min\.[0-9a-f]{12}\.js$')
                for sound in MATHLIVE_SOUNDS:
                    self.assertTrue((Path(root) / 'vendor/mathlive/sounds' / f'{sound}.wav').is_file(), sound)
                lib_url = static('vendor/modern-screenshot/modern-screenshot.js')
                self.assertRegex(lib_url, r'^/static/vendor/modern-screenshot/modern-screenshot\.[0-9a-f]{12}\.js$')
            staticfiles_storage._wrapped = empty


class BundledScriptsTests(SimpleTestCase):
    """Общие скрипты страниц — одним app.js (make build-js, JS_BASE в Makefile)."""

    BASE = ('math', 'katex_copy', 'autosave', 'image_paste', 'livefile', 'busy',
            'shell', 'dialogs', 'quick_clone', 'image_zoom', 'taxonomy')

    def test_base_template_loads_one_bundle(self):
        text = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        self.assertIn("{% static 'js/app.js' %}", text)
        for name in self.BASE:
            self.assertNotIn(f"'js/{name}.js'", text, name)

    def test_bundle_contains_every_base_script_in_order(self):
        bundle = finders.find('js/app.js')
        self.assertIsNotNone(bundle, 'нет static/js/app.js — make build-js')
        text = Path(bundle).read_text(encoding='utf-8')
        positions = [text.index(f'/* === public_html/static/js/{name}.js === */') for name in self.BASE]
        self.assertEqual(positions, sorted(positions))
        for name in self.BASE:
            source = Path(finders.find(f'js/{name}.js')).read_text(encoding='utf-8')
            self.assertIn(source.strip(), text, name)


class VendorPagesTests(TestCase):
    def test_pages_link_local_assets(self):
        login = self.client.get(reverse('login'))
        self.assertContains(login, '/static/vendor/inter/inter.css')
        self.assertContains(login, '/static/vendor/katex/katex.min.css')
        self.assertContains(login, '/static/vendor/katex/contrib/auto-render.min.js')
        for host in FORBIDDEN:
            self.assertNotContains(login, host)
        make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, '/static/vendor/katex/katex.min.js')
        self.assertContains(dashboard, 'data-lib="/static/vendor/modern-screenshot/modern-screenshot.js"')
        for host in FORBIDDEN:
            self.assertNotContains(dashboard, host)
        task_form = self.client.get(reverse('task_create'))
        self.assertContains(task_form, '/static/vendor/mathlive/mathlive.min.js')
        for host in FORBIDDEN:
            self.assertNotContains(task_form, host)
