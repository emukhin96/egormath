#!/usr/bin/env python3
"""Перенос черновиков после ручного деплоя. Не обновляет код сервера."""
import argparse
import hashlib
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True, **kwargs)


def transfer(package, host, remote_root, username):
    """Проверить установленную версию, доставить архив и загрузить транзакционно."""
    if not re.fullmatch(r'[\w.-]+@[\w.-]+', host):
        raise ValueError('Укажите SSH-хост в формате пользователь@сервер.')
    if not re.fullmatch(r'/[\w/.-]+', remote_root):
        raise ValueError('Недопустимый корневой каталог сервера.')
    python = remote_root + '/venv/bin/python'
    manage = remote_root + '/public_html/manage.py'
    ssh = ['ssh', '-o', 'ConnectTimeout=20', host]
    prefix = 'cd ' + shlex.quote(remote_root + '/public_html') + ' && '
    # Запрос к новому столбцу обнаруживает неприменённую миграцию до отправки архива.
    preflight = ('from problems.textbook_transfer import SCHEMA_VERSION, _resolve_owner; '
                 'from problems.models import TextbookImportBatch; '
                 'assert SCHEMA_VERSION == 2, "Нужен ручной деплой новой версии"; '
                 f'_resolve_owner({username!r}); '
                 'list(TextbookImportBatch.objects.values_list("transfer_key", flat=True)[:1])')
    run(ssh + [prefix + shlex.join([python, manage, 'shell', '-c', preflight])])
    remote_dir = run(ssh + ['mktemp -d /tmp/egormath-transfer.XXXXXXXX'], capture_output=True).stdout.strip()
    if not re.fullmatch(r'/tmp/egormath-transfer\.[A-Za-z0-9]+', remote_dir):
        raise ValueError('Сервер вернул неожиданный временный каталог.')
    remote_file = remote_dir + '/batch.zip'
    try:
        run(['scp', '-o', 'ConnectTimeout=20', str(package), host + ':' + remote_file])
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        check = ('import hashlib; '
                 f'assert hashlib.sha256(open({remote_file!r}, "rb").read()).hexdigest() == {digest!r}, '
                 '"Архив повреждён при передаче"')
        run(ssh + [shlex.join([python, '-c', check])])
        command = [python, manage, 'import_textbook_batches', remote_file, '--username', username]
        run(ssh + [prefix + shlex.join(command + ['--check-only'])])
        run(ssh + [prefix + shlex.join(command)])
    finally:
        # Только наш единственный файл и созданный нами пустой каталог.
        run(ssh + [shlex.join(['rm', '-f', remote_file]) + ' && ' + shlex.join(['rmdir', remote_dir])])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=int, nargs='?', help='Локальный ID партии')
    parser.add_argument('--package', type=Path, help='Повторить перенос готового ZIP')
    parser.add_argument('--username', default='egor', help='Учитель на принимающем сервере')
    parser.add_argument('--host', default='cs13661@vh426.timeweb.ru')
    parser.add_argument('--remote-root', default='/home/c/cs13661/egormath')
    parser.add_argument('--prepare-only', action='store_true', help='Только подготовить архив локально')
    options = parser.parse_args()
    if (options.batch is None) == (options.package is None):
        parser.error('Укажите либо ID партии, либо --package.')
    package = options.package.resolve() if options.package else None
    if package is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        package = ROOT / 'artifacts' / 'transfers' / f'batch-{options.batch}-{stamp}.zip'
        run([ROOT / 'venv/bin/python', ROOT / 'public_html/manage.py',
             'export_textbook_batches', package, '--batch', options.batch], cwd=ROOT)
    if not package.is_file() or package.suffix.lower() != '.zip':
        parser.error('Нужен существующий ZIP-пакет.')
    print(f'Архив: {package}', flush=True)
    print(f'SHA-256: {hashlib.sha256(package.read_bytes()).hexdigest()}', flush=True)
    if not options.prepare_only:
        transfer(package, options.host, options.remote_root, options.username)


if __name__ == '__main__':
    main()
