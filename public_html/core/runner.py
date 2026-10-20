"""Тестовый раннер: запас лимитов вычислителя формул на загруженной машине.

На проде одно вычисление формулы ограничено 3 с по часам
(formulas.WORKER_TIMEOUT) и 2 с процессора ребёнка (formula_worker.CPU_LIMIT,
на Linux). На загруженном CI-раннере тяжёлая эквивалентность (arcsin, корни,
области angle:) дольше ждёт процессор и считается медленнее, падает
FormulaUnavailable — и тест краснеет без изменений в коде.

В тестах лимиты подняты: по часам — до минуты (на macOS каждый ребёнок —
новый python, и под несколькими параллельными прогонами в папке Dropbox
одна проверка тянулась дольше 30 с), процессора — в десять раз. Вердикт
зависит от математики, а не от соседей по машине. Тесты самих лимитов
подменяют их явно.

Модуль назван не test*.py, чтобы discovery не принимал его за тесты.
"""
import os

from django.test.runner import DiscoverRunner

# Секунды по часам на одно вычисление формулы в тестах.
TEST_WORKER_TIMEOUT = 60
# Мягкий лимит процессора ребёнка в тестах, секунды.
TEST_CPU_LIMIT = 20


class TestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        from assignments.checks import formula_worker, formulas
        self._worker_timeout = formulas.WORKER_TIMEOUT
        formulas.WORKER_TIMEOUT = TEST_WORKER_TIMEOUT
        # Ребёнок — отдельный процесс (forkserver или subprocess): лимит
        # процессора доходит до него только через окружение.
        self._cpu_limit = os.environ.get(formula_worker.TEST_CPU_LIMIT_ENV)
        os.environ[formula_worker.TEST_CPU_LIMIT_ENV] = str(TEST_CPU_LIMIT)

    def teardown_test_environment(self, **kwargs):
        from assignments.checks import formula_worker, formulas
        formulas.WORKER_TIMEOUT = self._worker_timeout
        if self._cpu_limit is None:
            os.environ.pop(formula_worker.TEST_CPU_LIMIT_ENV, None)
        else:
            os.environ[formula_worker.TEST_CPU_LIMIT_ENV] = self._cpu_limit
        super().teardown_test_environment(**kwargs)
