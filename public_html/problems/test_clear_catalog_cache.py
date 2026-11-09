"""Срок жизни кэшей каталога и команда их сброса (контроль прода 09.11.2026)."""
from io import StringIO

from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command
from django.test import SimpleTestCase


class CatalogCacheTtlTests(SimpleTestCase):
    def test_timeouts_are_hours_not_minutes(self):
        # Сброс идёт сигналами; TTL — страховка, короткий TTL делал каждый
        # первый заход после перемены холодным (1–3 с на проде)
        for alias in ('taxonomy', 'catalog'):
            self.assertGreaterEqual(settings.CACHES[alias]['TIMEOUT'], 3600, alias)

    def test_command_clears_both_caches(self):
        caches['taxonomy'].set('probe', 1)
        caches['catalog'].set('probe', 2)
        out = StringIO()
        call_command('clear_catalog_cache', stdout=out)
        self.assertIsNone(caches['taxonomy'].get('probe'))
        self.assertIsNone(caches['catalog'].get('probe'))
        self.assertIn('taxonomy: сброшен', out.getvalue())
        self.assertIn('catalog: сброшен', out.getvalue())
