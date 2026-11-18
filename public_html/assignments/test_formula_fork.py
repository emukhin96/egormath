"""Вычислитель формул в процессе, порождённом fork после прогрева.

С #345 gunicorn грузит приложение в мастере (``preload_app``), и
``core/wsgi.py`` прогревает forkserver там же. Воркеры — fork мастера:
им достаётся чужой forkserver, ``multiprocessing`` делает ``waitpid`` не
своего ребёнка (``ChildProcessError``), и каждая проверка формулы на
проде отвечала «Проверка временно недоступна» (17.11.2026).
"""
import json
import os
import unittest

from django.test import SimpleTestCase

from .checks import formula_fork

PAYLOAD = json.dumps({'payload': 'x', 'multiple': False})


@unittest.skipUnless(hasattr(os, 'fork'), 'нужен os.fork')
class ForkedWorkerTests(SimpleTestCase):
    def run_in_fork(self):
        """Как воркер gunicorn: fork прогретого процесса, затем проверка."""
        read, write = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover — ребёнок отчитывается через pipe
            os.close(read)
            try:
                result = formula_fork.run_worker(PAYLOAD, 20)
                report = {'returncode': result.returncode,
                          'display': json.loads(result.stdout).get('display')}
            except BaseException as error:  # noqa: BLE001 — всё в отчёт
                report = {'error': f'{type(error).__name__}: {error!r} '
                                   f'(причина: {error.__cause__!r})'}
            os.write(write, json.dumps(report).encode())
            os.close(write)
            os._exit(0)
        os.close(write)
        chunks = []
        while chunk := os.read(read, 65536):
            chunks.append(chunk)
        os.close(read)
        os.waitpid(pid, 0)
        return json.loads(b''.join(chunks) or b'{}')

    def test_forked_process_starts_its_own_forkserver(self):
        formula_fork.warmup()  # forkserver — ребёнок этого процесса
        self.assertTrue(formula_fork._ready)
        report = self.run_in_fork()
        self.assertEqual(report, {'returncode': 0, 'display': 'x'})
        # Свой forkserver родителя после этого по-прежнему работает
        result = formula_fork.run_worker(PAYLOAD, 20)
        self.assertEqual(result.returncode, 0)
