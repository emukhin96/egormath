#!/usr/bin/env python3
"""Перенос черновиков на VPS после деплоя. Не обновляет код сервера."""
import argparse
import hashlib
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 3
# $DATA_DIR/var смонтирован в контейнер egormath-web как /app/var (deploy/vps/compose.yaml).
CONTAINER_VAR = '/app/var'
TEMP_DIR = re.compile(r'/[\w/.-]+/var/transfers/egormath-transfer\.[A-Za-z0-9]+')


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True, **kwargs)


def transfer(package, host, app_dir, username):
    """Проверить установленную версию, доставить архив и загрузить транзакционно."""
    if not re.fullmatch(r'\w[\w.-]*(@[\w.-]+)?', host):
        raise ValueError('Укажите SSH-хост: псевдоним из ~/.ssh/config или пользователь@сервер.')
    if not re.fullmatch(r'/[\w/.-]+', app_dir):
        raise ValueError('Недопустимый каталог приложения на сервере.')
    ssh = ['ssh', '-o', 'ConnectTimeout=20', host]
    # lib.sh берёт APP_DIR из окружения (по умолчанию /opt/egormath), а не из
    # пути к скрипту: без явной передачи .env, DATA_DIR и compose.yaml
    # взялись бы из другого каталога, чем manage.sh.
    manage = ['env', f'APP_DIR={app_dir}', app_dir + '/deploy/vps/manage.sh']
    # Запрос к новому столбцу обнаруживает неприменённую миграцию до отправки архива.
    preflight = ('from problems.textbook_transfer import SCHEMA_VERSION, _resolve_owner; '
                 'from problems.models import TextbookImportBatch; '
                 f'assert SCHEMA_VERSION == {SCHEMA_VERSION}, "Нужен деплой новой версии"; '
                 f'_resolve_owner({username!r}); '
                 'list(TextbookImportBatch.objects.values_list("transfer_key", flat=True)[:1])')
    run(ssh + [shlex.join(manage + ['shell', '-c', preflight])])
    # Каталог внутри $DATA_DIR/var, чтобы архив был виден из контейнера.
    make_dir = (f'export APP_DIR={shlex.quote(app_dir)} && '
                f'. {shlex.quote(app_dir + "/deploy/vps/lib.sh")} && '
                'mkdir -p "$DATA_DIR/var/transfers" && '
                'mktemp -d "$DATA_DIR/var/transfers/egormath-transfer.XXXXXXXX"')
    remote_dir = run(ssh + [shlex.join(['bash', '-c', make_dir])], capture_output=True).stdout.strip()
    if not TEMP_DIR.fullmatch(remote_dir) or '..' in remote_dir:
        raise ValueError('Сервер вернул неожиданный временный каталог.')
    remote_file = remote_dir + '/batch.zip'
    container_file = f'{CONTAINER_VAR}/transfers/{PurePosixPath(remote_dir).name}/batch.zip'
    try:
        run(['scp', '-o', 'ConnectTimeout=20', str(package), host + ':' + remote_file])
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        remote_digest = run(ssh + [shlex.join(['sha256sum', '--', remote_file])],
                            capture_output=True).stdout.split()[:1]
        if remote_digest != [digest]:
            raise ValueError('Архив повреждён при передаче.')
        command = manage + ['import_textbook_batches', container_file, '--username', username]
        run(ssh + [shlex.join(command + ['--check-only'])])
        run(ssh + [shlex.join(command)])
    finally:
        # Только наш единственный файл и созданный нами пустой каталог.
        run(ssh + [shlex.join(['rm', '-f', remote_file]) + ' && ' + shlex.join(['rmdir', remote_dir])])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=int, nargs='?', help='Локальный ID партии')
    parser.add_argument('--package', type=Path, help='Повторить перенос готового ZIP')
    parser.add_argument('--username', default='egor', help='Учитель на принимающем сервере')
    parser.add_argument('--host', default='chemolymp-demo', help='SSH-хост VPS (deploy/VPS.md)')
    parser.add_argument('--app-dir', default='/opt/egormath', help='Каталог egormath на сервере')
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
        transfer(package, options.host, options.app_dir, options.username)


if __name__ == '__main__':
    main()
