#!/usr/bin/env python3
"""CLI-обёртка общего парсера задачников из Django-приложения."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_HTML = PROJECT_ROOT / "public_html"
if str(PUBLIC_HTML) not in sys.path:
    sys.path.insert(0, str(PUBLIC_HTML))

from problems.textbook_parser import *  # noqa: E402,F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
