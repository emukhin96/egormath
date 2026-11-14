"""Прогрев процесса и воркера gunicorn (core/warmup.py,
deploy/vps/gunicorn.conf.py) — хуки не падают и делают то, что обещают."""
import runpy
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import caches
from django.db import connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from core import warmup

GUNICORN_CONF = Path(settings.SITE_ROOT) / 'deploy' / 'vps' / 'gunicorn.conf.py'


class WarmProcessTests(TestCase):
    def test_warm_process_parses_heavy_mask_without_db(self):
        with self.assertNumQueries(0):
            spec = warmup.warm_process()
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual([s.kind for s in spec.slots], ['number', 'range', 'expression'])
        from assignments.checks import expressions
        self.assertIsNotNone(expressions._lark()[0])


class GunicornConfigTests(SimpleTestCase):
    def load(self, env=None):
        with mock.patch.dict('os.environ', env or {}, clear=False):
            return runpy.run_path(str(GUNICORN_CONF))

    def test_config_values(self):
        conf = self.load({'GUNICORN_BIND': '127.0.0.1:9'})
        self.assertTrue(conf['preload_app'])
        self.assertEqual(conf['worker_class'], 'gthread')
        self.assertGreaterEqual(conf['max_requests'], 5000)
        self.assertEqual(conf['bind'], '127.0.0.1:9')

    def test_when_ready_warms_and_logs(self):
        conf = self.load()
        server = mock.Mock()
        with mock.patch('core.warmup.warm_process') as warm:
            conf['when_ready'](server)
        warm.assert_called_once_with()
        self.assertIn('warmup (master)', server.log.info.call_args[0][0])

    def test_warmup_can_be_disabled_and_never_raises(self):
        conf = self.load({'GUNICORN_WARMUP': '0'})
        with mock.patch('core.warmup.warm_process') as warm:
            conf['when_ready'](mock.Mock())
            conf['post_worker_init'](mock.Mock())
        warm.assert_not_called()
        conf = self.load()
        worker = mock.Mock()
        with mock.patch('core.warmup.warm_worker', side_effect=RuntimeError('нет базы')):
            conf['post_worker_init'](worker)  # не бросает
        self.assertIn('skipped', worker.log.info.call_args[0][0])


class WarmWorkerTests(TransactionTestCase):
    """Вне транзакции, как в воркере: кэши наполняются, соединение закрыто."""

    def setUp(self):
        caches['taxonomy'].clear()

    def tearDown(self):
        caches['taxonomy'].clear()

    def test_warm_open_masks_parses_only_open_runs(self):
        from django.contrib.auth.models import User
        from independentworks.models import Attempt, Point, Run, Variant, Work
        from problems.tests import make_student, make_teacher
        teacher = make_teacher()
        student = make_student(teacher)
        work = Work.objects.create(owner=teacher, title='СР')
        run = Run.objects.create(work=work, owner=teacher, title='СР', issued_at='2026-11-01T10:00Z')
        variant = Variant.objects.create(run=run, number=1)
        Point.objects.create(variant=variant, position=1, label='1', snapshot={'mask': '{{number: 5}}', 'text': 'x', 'answer': '5', 'solution': ''})
        Attempt.objects.create(run=run, variant=variant, student=student)
        with mock.patch('assignments.checks.mask.parse_mask', wraps=__import__('assignments.checks.mask', fromlist=['parse_mask']).parse_mask) as spy:
            self.assertEqual(warmup.warm_open_masks(), 1)
        spy.assert_called_once_with('{{number: 5}}')

    def test_warm_worker_fills_caches_and_closes_connection(self):
        # sqlite в памяти не закрывается по-настоящему — проверяем сам вызов
        with mock.patch('django.db.connections.close_all', wraps=connections.close_all) as close_all:
            warmup.warm_worker()
        close_all.assert_called_once_with()
        from problems.rubricator import taxonomy_catalog
        from worksheets.collection_catalog import catalog_nodes
        with self.assertNumQueries(0):
            catalog_nodes()
        # Каталог рубрикатора: справочники из кэша, свежими остаются только счётчики
        self.assertIn('topics', taxonomy_catalog())
