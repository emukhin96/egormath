"""Изолированные Linux-процессы с общей доверенной грамматикой.

Forkserver создаёт детей из собственного однопоточного процесса, поэтому
не наследует блокировки потоков gunicorn. Каждый ответ считается новым
процессом с прежними лимитами памяти/CPU; ввод не исполняется как Python.
"""
import io
import multiprocessing
import os
import subprocess
import sys
import time
import threading
import json


_startup_lock = threading.Lock()
_ready = False
_failed_until = 0
STARTUP_RETRY_DELAY = 10


class FormulaStartupUnavailable(RuntimeError):
    """Парсер не готов; ученический ввод ещё не запускался."""


def warmup():
    """Доверенный прогрев без очереди запросов и без блокировки их ввода.

    При отказе следующая попытка возможна через десять секунд. Запросы,
    пришедшие во время прогрева, сразу получают временную недоступность.
    """
    global _ready, _failed_until
    if _ready:
        return
    if not _startup_lock.acquire(blocking=False):
        raise FormulaStartupUnavailable('парсер формул запускается')
    try:
        if _ready:
            return
        if time.monotonic() < _failed_until:
            raise FormulaStartupUnavailable('повторный запуск парсера отложен')
        try:
            result = _run_process(json.dumps({'payload': 'x', 'multiple': False}), 10)
            response = json.loads(result.stdout)
            if result.returncode or not isinstance(response, dict) or not response.get('display'):
                raise ValueError('не удалось загрузить парсер формул')
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            _failed_until = time.monotonic() + STARTUP_RETRY_DELAY
            raise FormulaStartupUnavailable('парсер формул пока не готов') from error
        _ready = True
        _failed_until = 0
    finally:
        _startup_lock.release()


def _calculate(payload, connection):
    from .formula_worker import main
    sys.stdin = io.StringIO(payload)
    sys.stdout = io.StringIO()
    try:
        main()
        connection.send(sys.stdout.getvalue())
    finally:
        connection.close()


def run_worker(payload, timeout):
    """Прогреваем доверенный код, затем ограничиваем реальный ввод."""
    warmup()
    return _run_process(payload, timeout)


def _run_process(payload, timeout):
    """JSON-протокол; процесс всегда убирается, в том числе при таймауте."""
    global _ready, _failed_until
    from .formula_worker import HASH_SEED
    # Forkserver берёт окружение процесса, который его запускает, а дети —
    # хэши forkserver. Значение остаётся и для его перезапусков; хэши самого
    # веб-процесса уже выбраны при старте и не меняются. Первый вызов —
    # прогрев из core/wsgi.py, до приёма запросов потоками.
    if os.environ.get('PYTHONHASHSEED') != HASH_SEED:
        os.environ['PYTHONHASHSEED'] = HASH_SEED
    context = multiprocessing.get_context('forkserver')
    context.set_forkserver_preload(['assignments.checks.formula_preload'])
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_calculate, args=(payload, sender))
    started = False
    try:
        try:
            process.start()
        except (EOFError, RuntimeError, OSError) as error:
            # Forkserver может исчезнуть до передачи PID ребёнка. Приводим
            # этот отказ к общему протоколу ошибок запуска, как у subprocess.
            _ready = False
            _failed_until = time.monotonic() + STARTUP_RETRY_DELAY
            raise FormulaStartupUnavailable('не удалось запустить процесс проверки формул') from error
        started = True
        # Перезапуск forkserver загружает только доверенную грамматику.
        # Лимит реального ввода отсчитывается после успешного запуска ребёнка.
        deadline = time.monotonic() + timeout
        sender.close()
        remaining = max(0, deadline - time.monotonic())
        if not remaining or not receiver.poll(remaining):
            raise subprocess.TimeoutExpired('formula_worker', timeout)
        try:
            output = receiver.recv()
        except EOFError:
            output = ''
        process.join(max(0, deadline - time.monotonic()))
        if process.is_alive():
            raise subprocess.TimeoutExpired('formula_worker', timeout)
        return subprocess.CompletedProcess('formula_worker', process.exitcode, output, '')
    finally:
        receiver.close()
        sender.close()
        if started:
            if process.is_alive():
                process.kill()
            process.join()
        process.close()
