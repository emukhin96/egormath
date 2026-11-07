"""Inter, KaTeX и Sortable раздаются со своего сервера (static/vendor):
в шаблонах нет ссылок на Google Fonts и jsdelivr для них, а все файлы,
на которые ссылаются их CSS, есть в статике (аудит быстродействия 06.11.2026)."""
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
# MathLive и modern-screenshot пока грузятся с CDN (static/vendor/README.md)
FORBIDDEN = ('fonts.googleapis.com', 'fonts.gstatic.com',
             'cdn.jsdelivr.net/npm/katex', 'cdn.jsdelivr.net/npm/sortablejs')


class VendorTemplatesTests(SimpleTestCase):
    def test_templates_do_not_reference_moved_cdns(self):
        offenders = []
        for path in TEMPLATES_DIR.rglob('*.html'):
            text = path.read_text(encoding='utf-8')
            for host in FORBIDDEN:
                if host in text:
                    offenders.append((path.relative_to(TEMPLATES_DIR), host))
        self.assertEqual(offenders, [])

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
        for host in FORBIDDEN:
            self.assertNotContains(dashboard, host)
