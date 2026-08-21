#!/usr/bin/env python3
"""Патч /opt/latex-api/app.py для EgorMath.

Что делает:
  1. Два прогона lualatex (нумерация страниц thepage/pageref LastPage).
  2. Опциональное поле assets у tex_files (картинки задач).

Запуск на VPS (от root или с sudo):
  sudo python3 /tmp/patch_latex_api_egormath.py

Скрипт идемпотентен: повторный запуск не портит уже пропатченный файл.
Делает бэкап app.py рядом с собой (.bak-YYYYMMDD-HHMMSS).
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

APP_PATH = Path('/opt/latex-api/app.py')

NEW_COMPILE_TEX = '''def compile_tex(tex_content: str, output_name: str, assets=None) -> Path:
    """Компилирует LaTeX в PDF.

    Два прогона lualatex нужны для pageref{LastPage} (колонтитул egor: «2/5»).
    assets — опциональный список [{"filename": "...", "content_base64": "..."}]
    (картинки задач EgorMath); без него поведение как раньше.
    """
    compile_dir = Path(COMPILE_DIR)

    # Создаем уникальное имя для файла
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    tex_file = compile_dir / f"{output_name}_{timestamp}.tex"
    pdf_file = compile_dir / f"{output_name}_{timestamp}.pdf"

    # Сохраняем .tex файл
    tex_file.write_text(tex_content, encoding='utf-8')
    logger.info(f"Created .tex file: {tex_file}")

    # Картинки задач (EgorMath): рядом с .tex, без подкаталогов в имени
    MAX_ASSET_SIZE = 5 * 1024 * 1024
    MAX_ASSETS = 20
    for asset in (assets or []):
        if not isinstance(asset, dict):
            raise RuntimeError('asset must be an object')
    if assets and len(assets) > MAX_ASSETS:
        raise RuntimeError(f'too many assets (max {MAX_ASSETS})')
    for asset in (assets or []):
        filename = asset.get('filename', '')
        if (not filename or filename != os.path.basename(filename)
                or '/' in filename or '\\\\' in filename
                or filename.startswith('.')):
            raise RuntimeError(f'bad asset filename: {filename!r}')
        try:
            raw = base64.b64decode(asset.get('content_base64', ''), validate=True)
        except Exception as exc:
            raise RuntimeError(f'bad asset content: {filename}: {exc}')
        if len(raw) > MAX_ASSET_SIZE:
            raise RuntimeError(f'asset too large: {filename}')
        (compile_dir / filename).write_bytes(raw)
        logger.info(f"Wrote asset {filename} ({len(raw)} bytes)")

    # Команда компиляции
    cmd = [
        LUALATEX_PATH,
        '-interaction=nonstopmode',
        '-output-directory', str(compile_dir),
        str(tex_file)
    ]

    # Настраиваем переменные окружения для TeX Live
    env = os.environ.copy()
    # Добавить переменные окружения TeX Live если нужно

    try:
        # Первый прогон
        logger.info(f"Running (pass 1): {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=str(compile_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=LUALATEX_TIMEOUT
        )
        logger.info(f"LuaLaTeX pass 1 exit code: {result.returncode}")
        if result.returncode != 0:
            logger.error(f"LuaLaTeX compilation failed:\\n{result.stdout}")
            raise RuntimeError(f"LuaLaTeX compilation failed: {result.stdout[:3000]}")

        # Второй прогон — pageref LastPage в колонтитулах egor
        logger.info(f"Running (pass 2): {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=str(compile_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=LUALATEX_TIMEOUT
        )
        logger.info(f"LuaLaTeX pass 2 exit code: {result.returncode}")
        if result.returncode != 0:
            logger.error(f"LuaLaTeX pass 2 failed:\\n{result.stdout}")
            raise RuntimeError(f"LuaLaTeX pass 2 failed: {result.stdout[:3000]}")

        if not pdf_file.exists():
            raise RuntimeError("PDF file was not created")

        logger.info(f"PDF created successfully: {pdf_file} ({pdf_file.stat().st_size} bytes)")
        return pdf_file

    except subprocess.TimeoutExpired:
        logger.error(f"LuaLaTeX compilation timeout ({LUALATEX_TIMEOUT}s)")
        raise RuntimeError(f"Compilation timeout ({LUALATEX_TIMEOUT}s)")
    except Exception as e:
        logger.error(f"Compilation error: {type(e).__name__}: {e}")
        raise
'''

# Вызов compile_tex в эндпоинте /api/v1/compile-latex — прокинуть assets
OLD_CALL = re.compile(
    r'pdf_path\s*=\s*compile_tex\(\s*tex_content\s*,\s*f"team_\{team_id\}"\s*\)'
)
NEW_CALL = (
    'pdf_path = compile_tex(tex_content, f"team_{team_id}", '
    'assets=tex_file.get("assets"))'
)


def main() -> int:
    if not APP_PATH.exists():
        print(f'ERROR: {APP_PATH} не найден. Подставьте фактический путь.', file=sys.stderr)
        return 1

    src = APP_PATH.read_text(encoding='utf-8')

    # Бэкап всегда
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = APP_PATH.with_suffix(f'.py.bak-{stamp}')
    shutil.copy2(APP_PATH, backup)
    print(f'Backup: {backup}')

    # Уже пропатчено?
    already_two_pass = 'Running (pass 2)' in src or 'pass 2' in src
    already_assets = 'assets=tex_file.get("assets")' in src or "assets=tex_file.get('assets')" in src

    if already_two_pass and already_assets:
        # Убрать SyntaxWarning от docstring с \pageref, если остался от старой версии патча
        cleaned = src.replace(
            'для \\pageref{LastPage}', 'для pageref{LastPage}'
        ).replace(
            'для \pageref{LastPage}', 'для pageref{LastPage}'
        ).replace(
            '— \\pageref{LastPage} в', '— pageref LastPage в'
        ).replace(
            '— \pageref{LastPage} в', '— pageref LastPage в'
        )
        if cleaned != src:
            APP_PATH.write_text(cleaned, encoding='utf-8')
            print('Уже пропатчено; поправил docstring (SyntaxWarning).')
        else:
            print('Уже пропатчено (два прогона + assets). Ничего не меняю.')
        return 0

    # Замена функции compile_tex целиком (от def до следующего def merge_pdfs)
    func_re = re.compile(
        r'^def compile_tex\(.*?\n(?=^def merge_pdfs\()',
        re.MULTILINE | re.DOTALL,
    )
    if not func_re.search(src):
        print('ERROR: не нашёл def compile_tex ... def merge_pdfs', file=sys.stderr)
        print('Откройте app.py и примените патч вручную (см. DEPLOY.md).', file=sys.stderr)
        return 2

    # re.sub трактует \ в строке замены как escape — подставляем через lambda
    replacement = NEW_COMPILE_TEX.rstrip() + '\n\n\n'
    src = func_re.sub(lambda _m: replacement, src, count=1)

    if not OLD_CALL.search(src):
        # возможно уже обновлён вызов или другой формат
        if 'assets=tex_file.get' not in src:
            print('WARNING: не нашёл вызов compile_tex(tex_content, f"team_{team_id}").')
            print('Добавьте вручную: assets=tex_file.get("assets")')
    else:
        src = OLD_CALL.sub(NEW_CALL, src, count=1)

    # base64 и os уже импортируются в исходном app.py (проверено)
    for needed in ('import base64', 'import os', 'import subprocess'):
        if needed not in src:
            print(f'WARNING: в app.py нет `{needed}` — добавьте в начало файла.')

    APP_PATH.write_text(src, encoding='utf-8')
    print(f'Patched: {APP_PATH}')
    print('Дальше: sudo systemctl restart latex-api')
    return 0


if __name__ == '__main__':
    sys.exit(main())
