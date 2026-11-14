"""Файловый кэш с редкой чисткой (core/cache_backends.py): каталог
перечисляется раз в CULL_EVERY записей, а не при каждой."""
import os
import tempfile
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from core.cache_backends import SparseCullFileBasedCache


class SparseCullTests(SimpleTestCase):
    def make(self, **options):
        return SparseCullFileBasedCache(tempfile.mkdtemp(prefix='egormath-sparse-'),
                                        {'TIMEOUT': None, 'OPTIONS': options})

    def test_directory_is_listed_once_per_cull_every_sets(self):
        cache = self.make(CULL_EVERY=4, MAX_ENTRIES=1000)
        with mock.patch.object(SparseCullFileBasedCache, '_list_cache_files',
                               wraps=cache._list_cache_files) as listing:
            for i in range(9):
                cache.set(f'k{i}', i)
        # первая запись, затем каждая четвёртая: 1, 5, 9
        self.assertEqual(listing.call_count, 3)
        self.assertEqual([cache.get(f'k{i}') for i in range(9)], list(range(9)))

    def test_still_culls_when_over_limit(self):
        cache = self.make(CULL_EVERY=2, MAX_ENTRIES=3, CULL_FREQUENCY=0)
        for i in range(8):
            cache.set(f'k{i}', i)
        files = [f for f in os.listdir(cache._dir) if f.endswith(cache.cache_suffix)]
        self.assertLess(len(files), 8)

    def test_numeric_cache_uses_sparse_backend(self):
        conf = settings.CACHES['numeric']
        self.assertEqual(conf['BACKEND'], 'core.cache_backends.SparseCullFileBasedCache')
        self.assertGreaterEqual(conf['OPTIONS']['CULL_EVERY'], 100)
