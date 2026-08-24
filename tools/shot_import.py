"""Проверка PR F: предпросмотр импорта — per-subitem поля, toggle, bulk."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402

STATIC = os.path.abspath('staticfiles')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), 'shots'))
os.makedirs(OUT, exist_ok=True)

TEX = r'''\begin{document}
\bighead{Дроби}{8 класс}{И. Иванов}
\rubr{Разминка}
\task{1}{0}{Вычислите $\frac{1}{2}+\frac{1}{3}$.}[][{$\frac56$}]
\task{2}{2}{Найдите значение:}[{\item $2+2$; \item $3\cdot(1+2)$.}]
\end{document}
'''

teacher = User.objects.filter(profile__role='teacher').first()
client = Client(SERVER_NAME='localhost')
client.force_login(teacher)

html = client.post('/worksheets/import/',
                   {'tex': TEX, 'action': 'preview'}).content.decode()
html = re.sub(r'(href|src)="/static/', rf'\1="file://{STATIC}/', html)

with open(f'{OUT}/import_default.html', 'w') as f:
    f.write(html)

# Второй кадр: тумблер включён, первая задача выделена (панель массовых
# действий видна), вторая помечена «удалить из импорта»
demo = html.replace('id="import-create-form"',
                    'id="import-create-form" class="show-answers"')
demo = demo.replace('data-index="1"', 'data-index="1" checked')
demo = demo.replace('data-import-row="2"',
                    'data-import-row="2" class="import-skipped"')
skip_pos = demo.rfind('<span class="import-skip-state" hidden>')
demo = (demo[:skip_pos]
        + demo[skip_pos:].replace(
            '<span class="import-skip-state" hidden>',
            '<span class="import-skip-state">', 1))
with open(f'{OUT}/import_demo.html', 'w') as f:
    f.write(demo)

for name in ('import_default', 'import_demo'):
    subprocess.run([
        CHROME, '--headless', '--disable-gpu', '--hide-scrollbars',
        f'--screenshot={OUT}/{name}.png', '--window-size=1400,1100',
        '--virtual-time-budget=8000', f'file://{OUT}/{name}.html',
    ], check=True, capture_output=True)
    print(name, 'ok')
