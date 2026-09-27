"""Проверка живости egormath-web для Docker и deploy.sh.

GET http://127.0.0.1:8000/healthz с первым именем из ALLOWED_HOSTS
(иначе Django ответит 400 DisallowedHost). Код выхода 0 — всё в порядке.
"""
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

hosts = os.environ.get('ALLOWED_HOSTS')
if not hosts:
    try:
        hosts = Path('/app/.secrets/ALLOWED_HOSTS').read_text(encoding='utf-8-sig')
    except OSError:
        hosts = 'localhost'
host = next((h.strip() for h in hosts.split(',') if h.strip() and not h.strip().startswith('.')), 'localhost')

request = urllib.request.Request(
    'http://127.0.0.1:8000/healthz',
    headers={'Host': host, 'X-Forwarded-Proto': 'https'},
)
try:
    with urllib.request.urlopen(request, timeout=8) as response:
        print(response.read().decode()[:200])
        sys.exit(0 if response.status == 200 else 1)
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode()[:200])
except OSError as error:
    print(error)
sys.exit(1)
