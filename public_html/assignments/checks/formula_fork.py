"""Изолированные Linux-процессы с общей доверенной грамматикой.

Forkserver создаёт детей из собственного однопоточного процесса, поэтому
не наследует блокировки потоков gunicorn. Каждый ответ считается новым
процессом с прежними лимитами памяти/CPU; ввод не исполняется как Python.
"""
import io
import multiprocessing
import subprocess
import sys
import time
import threading
import json


_startup_lock = threading.Lock()
_ready = False


def warmup():
    """Один доверенный эталон до начала проверки ученического ввода.

    Прогрев ограничен десятью секундами и не содержит пользовательских
    данных. При сбое готовность не кешируется: следующий вызов повторит
    попытку. Каждый реальный ввод получает отдельный прежний таймаут.
    """
    global _ready
    with _startup_lock:
        if _ready:
            return
        result = _run_process(json.dumps({'payload': 'x', 'multiple': False}), 10)
        if result.returncode or not json.loads(result.stdout).get('display'):
            raise ValueError('не удалось загрузить парсер формул')
        _ready = True


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
    context = multiprocessing.get_context('forkserver')
    context.set_forkserver_preload(['assignments.checks.formula_preload'])
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_calculate, args=(payload, sender))
    deadline = time.monotonic() + timeout
    started = False
    try:
        process.start()
        started = True
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
