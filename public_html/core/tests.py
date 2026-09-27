"""Хранилище статики с хэшем в имени: collectstatic проходит, ссылки хэшируются."""
import tempfile

from django.core.management import call_command
from django.templatetags.static import static
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.functional import empty


class HashedStaticFilesStorageTests(SimpleTestCase):
    def test_collectstatic_hashes_css_and_js(self):
        with tempfile.TemporaryDirectory() as root:
            storages = {
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'core.staticfiles.HashedStaticFilesStorage'},
            }
            with override_settings(STATIC_ROOT=root, STORAGES=storages):
                from django.contrib.staticfiles.storage import staticfiles_storage
                staticfiles_storage._wrapped = empty  # пересоздать ленивый объект под override
                call_command('collectstatic', interactive=False, verbosity=0)
                self.assertRegex(static('css/app.css'), r'^/static/css/app\.[0-9a-f]{12}\.css$')
                self.assertRegex(static('js/canvas.js'), r'^/static/js/canvas\.[0-9a-f]{12}\.js$')
                # Файла нет — обычный путь, а не 500
                self.assertEqual(static('js/no-such-file.js'), '/static/js/no-such-file.js')
            staticfiles_storage._wrapped = empty


class HealthzTests(TestCase):
    """/healthz для deploy/vps: без входа, 200 при живой базе и каталоге live/."""

    def test_ok(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'db': 'ok', 'live': 'ok'})
        self.assertIn('no-cache', response['Cache-Control'])

    def test_live_dir_missing(self):
        with override_settings(LIVE_FILE_DIR='/nonexistent/egormath-live'):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['live'], 'error')
