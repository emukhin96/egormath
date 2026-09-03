# Деплой egormath-web на Timeweb

> **Статус: отложено, документ справочный.** Сейчас работа идёт локально с
> ревью через GitHub PR — актуальный процесс описан в
> [docs/PIPELINE.md](../docs/PIPELINE.md). Вернуться к этой инструкции, когда
> дойдём до публикации на Timeweb.

Схема повторяет проверенную конфигурацию chgkmsu: shared-хостинг Timeweb
(`vh438.timeweb.ru`, аккаунт `cs13661`), Django через CGI-подобный WSGI
(`public_html/wsgi.py` + `.htaccess`), MySQL, автодеплой cron + `auto_pull.sh`.

Ниже `<site>` — имя каталога сайта на сервере (например, `~/egormath`).

## 0. Что нужно подготовить заранее

- [ ] Домен/поддомен, привязанный в панели Timeweb к каталогу `<site>`.
- [ ] MySQL-база в панели Timeweb: имя, пользователь, пароль.
- [ ] Ключ LaTeX API (см. раздел 4) — существующий из chgkmsu или отдельный.
- [ ] Deploy key или доступ к приватному репозиторию GitHub с сервера
  ```
  (`ssh-keygen` на сервере → добавить ключ в GitHub → Deploy keys, read-only).
  ```



## 1. LaTeX API-сервер (VPS 81.200.147.78)

Сервис уже развёрнут для chgkmsu (`/opt/latex-api/`, systemd `latex-api`,
порт 8000). Для egormath нужно **добавить пакет и шрифты**, не поднимать
сервис заново. Пакет `egor.sty` локально проверен под LuaLaTeX.

### 1.0. Что переносить (чеклист файлов)


| Файл / каталог                     | Откуда (Mac)                                              | Куда на VPS                         | Обязательность                                    |
| ---------------------------------- | --------------------------------------------------------- | ----------------------------------- | ------------------------------------------------- |
| `egor.sty`                         | `~/…/LaTEX/egormath/egor.sty`                             | `TEXMFLOCAL/.../egor/egor.sty`      | **Обязательно**                                   |
| CMU Serif/Sans/Typewriter (`.otf`) | `~/Library/Fonts/cmun*.otf` **или** TeX Live `cm-unicode` | системные шрифты + luaotfload       | **Обязательно** (профиль `font=cm`, дефолт сайта) |
| SchoolBookC + TextBookC (`.ttf`)   | `~/Library/Fonts/SchoolBookC*.ttf`, `TextBookC*.ttf`      | `/usr/local/share/fonts/egor/`      | Опционально (`font=school` / `font=palatino`)     |
| `chem.sty`                         | `LaTEX/egormath/chem.sty`                                 | рядом с `egor.sty`                  | Опционально (опция `[chem]`)                      |
| TeX Live `beamer`                  | коллекция `collection-latexextra` / пакет `beamer`        | дерево TeX Live на VPS              | **Обязательно для презентаций** (`beamer.cls`)    |
| `egorbeamer.sty`                   | `public_html/worksheets/tex/egorbeamer.sty`               | asset каждой сборки; опционально TEXMFLOCAL | Сайт шлёт sty сам; на TEXMFLOCAL — чтобы не занимать слот assets |
| `home.jpeg`, `kolba-round.png`     | если есть у вас                                           | `/opt/latex-api/compile/` или TEXMF | Опционально (`\home`, `\kolba`)                   |


Не нужны на API: `egormath.sty`, `mathneo.sty` (legacy), исходники
`egor-doc.tex`, тесты, PDF демо. Веб-генератор шлёт готовый `.tex` с
`\usepackage{egor}` — API только компилирует.

Пути на Mac (проверенные):

```bash
EGOR_SRC=~/Library/CloudStorage/Dropbox/code/LaTEX/egormath
FONTS_SRC=~/Library/Fonts
VPS=root@81.200.147.78   # или ваш SSH-alias / пользователь с sudo
```



### 1.1. Пакет egor.sty → TEXMFLOCAL

На Mac — упаковать и отправить:

```bash
# с Mac
scp "$EGOR_SRC/egor.sty" "$VPS:/tmp/egor.sty"
# опционально chem:
# scp "$EGOR_SRC/chem.sty" "$VPS:/tmp/chem.sty"
```

На VPS — установить в дерево TeX (видит любой `lualatex` через kpathsea):

```bash
# на VPS
sudo mkdir -p /usr/local/texlive/texmf-local/tex/latex/egor
sudo cp /tmp/egor.sty /usr/local/texlive/texmf-local/tex/latex/egor/
# sudo cp /tmp/chem.sty /usr/local/texlive/texmf-local/tex/latex/egor/   # если нужно
sudo mktexlsr

# проверка
kpsewhich egor.sty
# ожидается: .../texmf-local/tex/latex/egor/egor.sty
```

Альтернатива, если нет прав на `texmf-local`: положить `egor.sty` в
`/opt/latex-api/texmf/` и в `app.py` при вызове `lualatex` добавить в `env`:

```python
env['TEXINPUTS'] = '/opt/latex-api/texmf//' + os.pathsep + env.get('TEXINPUTS', '')
```

(предпочтительнее всё же TEXMFLOCAL — не трогает код API).

Обновление пакета позже: снова `scp` + `cp` + `mktexlsr`. Рестарт
`latex-api` не обязателен (пакет читается с диска при каждой компиляции).

### 1.1a. Beamer для презентаций листков

Сайт собирает презентации через `\documentclass{beamer}` и пакет
`egorbeamer.sty` (лежит в репозитории, уходит asset'ом в каталог сборки).
На API должен быть класс Beamer — иначе все сборки падают с
`File beamer.cls not found`.

```bash
# на VPS (TeX Live)
sudo tlmgr install beamer pgf translator
kpsewhich beamer.cls
# ожидается: .../texmf-dist/tex/latex/beamer/beamer.cls
```

`egorbeamer.sty` и `egorbeamer-grid.sty` ставить в TEXMFLOCAL не
обязательно: сайт прикладывает оба файла к каждому запросу. Хром
презентации (и клетка темы `grid`) подключает TikZ (идёт вместе с
`pgf`). Когда тема устаканится:

```bash
# с Mac
scp public_html/worksheets/tex/egorbeamer.sty "$VPS:/tmp/egorbeamer.sty"
# на VPS
sudo mkdir -p /usr/local/texlive/texmf-local/tex/latex/egor
sudo cp /tmp/egorbeamer.sty /usr/local/texlive/texmf-local/tex/latex/egor/
sudo mktexlsr
kpsewhich egorbeamer.sty
```

### 1.2. Шрифты CMU (обязательно для дефолтного `font=cm`)

Сначала проверить, есть ли они уже в TeX Live на VPS:

```bash
# на VPS
kpsewhich cmunrm.otf
luaotfload-tool --find="CMU Serif" 2>&1 | head -5
```

Если `kpsewhich` находит файл, а `luaotfload-tool --find` пишет `found` —
шрифты ставить не нужно, переходите к п. 1.4.

Если не находит — скопировать с Mac (у вас они уже в `~/Library/Fonts/`):

```bash
# с Mac
cd "$FONTS_SRC"
tar czf /tmp/cmun-fonts.tar.gz cmun*.otf
scp /tmp/cmun-fonts.tar.gz "$VPS:/tmp/"
```

```bash
# на VPS
sudo mkdir -p /usr/local/share/fonts/cmu
sudo tar xzf /tmp/cmun-fonts.tar.gz -C /usr/local/share/fonts/cmu
sudo chmod -R a+rX /usr/local/share/fonts/cmu
sudo fc-cache -f
fc-list | grep -i 'CMU Serif' | head
```



### 1.3. Шрифты SchoolBookC / TextBookC (опционально)

Нужны только если будете собирать листки с `\usepackage[font=school]{egor}`
или `font=palatino`. Сейчас веб-генератор использует дефолт `font=cm`.

```bash
# с Mac
cd "$FONTS_SRC"
tar czf /tmp/schoolbook-fonts.tar.gz SchoolBookC*.ttf TextBookC*.ttf
scp /tmp/schoolbook-fonts.tar.gz "$VPS:/tmp/"
```

```bash
# на VPS
sudo mkdir -p /usr/local/share/fonts/egor
sudo tar xzf /tmp/schoolbook-fonts.tar.gz -C /usr/local/share/fonts/egor
sudo chmod -R a+rX /usr/local/share/fonts/egor
sudo fc-cache -f
fc-list | grep -iE 'SchoolBook|TextBook' | head
```

Имена для fontspec должны совпасть с теми, что в `egor.sty`:
`SchoolBookC`, `SchoolBookC Bold`, `SchoolBookC Italic`,
`SchoolBookC Bold Italic`, `TextBookC`. Проверка:

```bash
fc-list : family | grep -i SchoolBook
# если family называется иначе — либо переименовать файлы / поставить
# правильные имена через fonts.conf, либо поправить egor.sty под фактические имена
```



### 1.4. База luaotfload (обязательно после любых шрифтов)

Компиляция идёт от пользователя сервиса `latex-api` (см.
`/opt/latex-api/systemd/latex-api.service` → `User=`). Кэш должен
строиться **под ним**, иначе «CMU Serif cannot be found» / «no writeable
cache path».

```bash
# на VPS — узнать пользователя
grep -E '^User=' /etc/systemd/system/latex-api.service
# типично: latex-api или www-data

API_USER=latex-api   # подставьте фактического

# каталог кэша должен быть доступен на запись
sudo -u "$API_USER" mkdir -p ~/.texlive/*/texmf-var 2>/dev/null || true
sudo -u "$API_USER" luaotfload-tool --update

sudo -u "$API_USER" luaotfload-tool --find="CMU Serif"
# ожидается: Font "CMU Serif" found!
```



### 1.5. Два прогона lualatex + assets (нумерация и картинки)

**Диагноз (проверено 2026-08-05).** В egor колонтитул —
`\thepage/\pageref{LastPage}` (`egor.sty`). После **одного** прогона
lualatex получается `2/??`; после **двух** — `2/2`. На API в
`compile_tex` (`/opt/latex-api/app.py`) сейчас **один** вызов
`subprocess.run(lualatex…)`. Django-кэш PDF (`WorksheetPdf`) не виноват:
он один раз получает уже готовый PDF от API и отдаёт его повторно. Пока API
отдаёт `??`, кэш только закрепляет ошибку; после патча API нужно
перегенерировать PDF (изменить листок или удалить записи `WorksheetPdf`).

Картинки задач сайт шлёт в том же запросе полем `assets` у элемента
`tex_files` (см. п. 1.6a). Оба исправления удобно накатить одним скриптом
из репозитория egormath-web — достаточно SSH на VPS.

#### Шаг A. Скопировать патч с Mac на VPS

```bash
# с Mac (из каталога egormath-web)
VPS=root@81.200.147.78   # ваш SSH-логин / alias
scp deploy/patch_latex_api_egormath.py "$VPS:/tmp/"
```

#### Шаг B. На VPS — бэкап, патч, перезапуск

```bash
# на VPS
ssh root@81.200.147.78

# убедиться, что сервис и файл на месте
systemctl status latex-api --no-pager | head -15
ls -la /opt/latex-api/app.py
grep -n 'def compile_tex' /opt/latex-api/app.py

# применить (идемпотентно; бэкап app.py.bak-… создаётся рядом)
sudo python3 /tmp/patch_latex_api_egormath.py
# ожидается: Backup: … / Patched: /opt/latex-api/app.py
# или: Уже пропатчено …

# синтаксис Python
python3 -m py_compile /opt/latex-api/app.py && echo OK

# перезапуск
sudo systemctl restart latex-api
sudo systemctl status latex-api --no-pager | head -20
curl -s http://127.0.0.1:8000/health
# {"status":"ok","lualatex_available":true,...}
```

Что меняет скрипт:
1. Функция `compile_tex` — **два** прогона lualatex; опциональный аргумент
   `assets=…` (пишет файлы в каталог компиляции до первого прогона).
2. Вызов в `/api/v1/compile-latex` —
   `compile_tex(..., assets=tex_file.get("assets"))`.

Откат при проблемах:

```bash
# на VPS — взять самый свежий бэкап
ls -lt /opt/latex-api/app.py.bak-* | head
sudo cp /opt/latex-api/app.py.bak-YYYYMMDD-HHMMSS /opt/latex-api/app.py
sudo systemctl restart latex-api
```

#### Шаг C. Проверка нумерации через HTTP (с Mac)

Многостраничный листок (один `\newpage` достаточно, чтобы увидеть
колонтитул на стр. 2). Ключ — из `.secrets/LATEX_API_KEY` сайта
или chgkmsu (не коммитьте его).

```bash
# с Mac
python3 - <<'PY'
import base64, pathlib, requests, subprocess, tempfile, os

key = pathlib.Path(
    # egormath-web или chgkmsu — где лежит ваш ключ:
    '/Users/emukhin96/Library/CloudStorage/Dropbox/code/egormath-web/.secrets/LATEX_API_KEY'
).read_text().strip()
# запасной путь:
# key = pathlib.Path.home().joinpath(
#     'Library/CloudStorage/Dropbox/code/chgkmsu/.secrets/LATEX_API_KEY').read_text().strip()

tex = r'''\documentclass[a5paper,10pt]{article}
\usepackage{egor}
\begin{document}
\bighead{Проверка нумерации}{8 класс}{Тест}
\begin{enumerate}
\task{1}{0}{Первая задача на странице 1.}
\end{enumerate}
\newpage
\begin{enumerate}[resume]
\task{1}{0}{Вторая задача на странице 2 — смотрим колонтитул.}
\end{enumerate}
\end{document}
'''
r = requests.post(
    'http://81.200.147.78:8000/api/v1/compile-latex',
    json={'api_key': key, 'tex_files': [{'team_id': 'pages', 'tex_content': tex}]},
    timeout=120,
)
j = r.json()
assert j.get('success'), j.get('error') or j.get('log', '')[:500]
pdf = base64.b64decode(j['pdf_base64'])
path = pathlib.Path('/tmp/egor-pages-check.pdf')
path.write_bytes(pdf)
print('pages:', j.get('total_pages'), 'bytes:', len(pdf))
text = subprocess.check_output(['pdftotext', '-layout', str(path), '-'], text=True)
print('has ?? :', '??' in text)
print('footer-like lines:')
for line in text.splitlines():
    if '/' in line and any(c.isdigit() for c in line):
        print(repr(line))
# Ожидается: has ?? : False  и строка вроде '2/2'
PY
```

Если всё ещё `2/??` — патч не применился или сервис не перезапущен
(`journalctl -u latex-api -n 50`). После успеха перегенерируйте PDF на
сайте (любое изменение листка или удаление кэша `WorksheetPdf`).

### 1.6. Проверка на VPS (без Django)

```bash
# на VPS
cat > /tmp/egor-smoke.tex <<'EOF'
\documentclass[a5paper,10pt]{article}
\usepackage{egor}
\begin{document}
\bighead{Проверка API}{8 класс}{Тест}
\rubr{Разминка}
\task{1}{0}{Решите уравнение $x^2-5x+6=0$.}[][2; 3]
\end{enumerate}
\end{document}
EOF

cd /tmp
sudo -u "$API_USER" lualatex -interaction=nonstopmode egor-smoke.tex
sudo -u "$API_USER" lualatex -interaction=nonstopmode egor-smoke.tex
ls -la egor-smoke.pdf
# в логе не должно быть "! Package fontspec Error"
```

Проверка через HTTP (ключ из `/opt/latex-api/config.py`):

```bash
# на VPS или с Mac
curl -s http://81.200.147.78:8000/health

# с Mac (подставьте ключ из chgkmsu/.secrets/LATEX_API_KEY)
python3 - <<'PY'
import json, base64, pathlib, requests
key = pathlib.Path.home().joinpath(
    'Library/CloudStorage/Dropbox/code/chgkmsu/.secrets/LATEX_API_KEY'
).read_text().strip()
tex = pathlib.Path('/tmp/egor-smoke.tex').read_text()  # или вставьте тот же smoke
r = requests.post(
    'http://81.200.147.78:8000/api/v1/compile-latex',
    json={'api_key': key, 'tex_files': [{'team_id': 'smoke', 'tex_content': tex}]},
    timeout=120,
)
print(r.status_code, r.json().keys() if r.ok else r.text[:500])
if r.ok and r.json().get('success'):
    pathlib.Path('/tmp/egor-api-smoke.pdf').write_bytes(
        base64.b64decode(r.json()['pdf_base64']))
    print('wrote /tmp/egor-api-smoke.pdf')
PY
```



### 1.6a. Поле `assets` (картинки задач) — детали

Сайт (после патча п. 1.5) передаёт картинки вместе с `.tex`:

```json
{
  "api_key": "…",
  "tex_files": [{
    "team_id": "ws12-student",
    "tex_content": "\\documentclass…\\taskpic{рис1.png}…",
    "assets": [
      {"filename": "рис1.png", "content_base64": "<base64>"}
    ]
  }]
}
```

Правила на API (уже в `patch_latex_api_egormath.py`):
- поле опциональное — запросы без `assets` как раньше (chgkmsu не ломается);
- не больше 20 файлов, каждый ≤ 5 МБ;
- `filename` — только имя файла (без `/`, `..`, скрытых имён);
- файл пишется в каталог компиляции **до** первого `lualatex`.

#### Проверка assets с Mac (после шагов A–B из п. 1.5)

```bash
python3 - <<'PY'
import base64, pathlib, requests
from PIL import Image
import io

key = pathlib.Path(
    '/Users/emukhin96/Library/CloudStorage/Dropbox/code/egormath-web/.secrets/LATEX_API_KEY'
).read_text().strip()

buf = io.BytesIO()
Image.new('RGB', (80, 40), 'white').save(buf, format='PNG')
png_b64 = base64.b64encode(buf.getvalue()).decode()

tex = r'''\documentclass[a5paper,10pt]{article}
\usepackage{egor}
\begin{document}
\bighead{Картинка}{8 класс}{Тест}
\begin{enumerate}
\task{1}{0}{Смотрите рисунок.\taskpic{smoke.png}}
\end{enumerate}
\flushpics
\end{document}
'''
r = requests.post(
    'http://81.200.147.78:8000/api/v1/compile-latex',
    json={'api_key': key, 'tex_files': [{
        'team_id': 'asset-smoke',
        'tex_content': tex,
        'assets': [{'filename': 'smoke.png', 'content_base64': png_b64}],
    }]},
    timeout=120,
)
j = r.json()
print('success:', j.get('success'), 'pages:', j.get('total_pages'))
if not j.get('success'):
    print((j.get('log') or j.get('error') or r.text)[:2000])
else:
    pathlib.Path('/tmp/egor-asset-smoke.pdf').write_bytes(
        base64.b64decode(j['pdf_base64']))
    print('wrote /tmp/egor-asset-smoke.pdf')
PY
```

До патча листок с `\taskpic` падает с «File `…` not found»; без картинок
компиляция работает как раньше.

#### Если скрипт патча не подходит (ручная правка по SSH)

```bash
ssh root@81.200.147.78
sudo cp /opt/latex-api/app.py /opt/latex-api/app.py.bak-manual
sudo nano /opt/latex-api/app.py   # или vim
```

1. Сигнатуру `def compile_tex(tex_content: str, output_name: str)` заменить на
   `def compile_tex(tex_content: str, output_name: str, assets=None)`.
2. Сразу после `tex_file.write_text(...)` вставить запись assets (см. тело
   функции в `deploy/patch_latex_api_egormath.py`, блок `MAX_ASSET_SIZE`).
3. После успешного первого `subprocess.run` добавить **второй** такой же вызов.
4. В эндпоинте `compile-latex` заменить
   `compile_tex(tex_content, f"team_{team_id}")` на
   `compile_tex(tex_content, f"team_{team_id}", assets=tex_file.get("assets"))`.
5. `python3 -m py_compile /opt/latex-api/app.py && sudo systemctl restart latex-api`.

### 1.7. Возможные проблемы


| Симптом                          | Решение                                                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `File beamer.cls not found`      | на API нет Beamer: `tlmgr install beamer` (и зависимости: `pgf`, `translator`, `etoolbox`) + `mktexlsr`       |
| `File egor.sty not found`        | `mktexlsr` не сделан; проверить `kpsewhich egor.sty`                                                          |
| `CMU Serif cannot be found`      | шрифты не в fontconfig или не обновлён luaotfload **под API_USER**                                            |
| `no writeable cache path`        | нет прав на `TEXMFVAR` у API_USER; создать домашний кэш, не ломать TEXMFVAR                                   |
| `mathspec` / ошибки под lualatex | у вас дефолт `font=cm` идёт через `fontspec`, не `mathspec` — ок; падают только `font=school`/`palatino`      |
| `2/??` в колонтитуле             | один прогон lualatex на API — п. 1.5 (`patch_latex_api_egormath.py`); затем сбросить кэш WorksheetPdf         |
| 401                              | ключ в `.secrets/LATEX_API_KEY` сайта ≠ `API_KEY` в `/opt/latex-api/config.py`; `systemctl restart latex-api` |
| Таймаут 60 с                     | длинный листок; поднять `LUALATEX_TIMEOUT` в `config.py`                                                      |




## 2. Первичная установка на shared-хостинге

```bash
ssh cs13661@vh438.timeweb.ru

# 1) Клонируем репозиторий (каталог сайта создаёт панель Timeweb)
cd ~ && git clone git@github.com:emukhin96/egormath.git <site>

# 2) Виртуальное окружение (Python 3.10)
cd <site>
python3.10 -m venv venv
venv/bin/pip install -r requirements.txt

# 3) Секреты — ДО первого запуска с DEBUG=False
mkdir -p .secrets && chmod 700 .secrets
echo "production"                      > .secrets/DJANGO_ENV
python3 -c "import secrets; print(secrets.token_urlsafe(50))" > .secrets/DJANGO_SECRET_KEY
echo "мой-домен.ru,www.мой-домен.ru"   > .secrets/ALLOWED_HOSTS
echo "<имя базы>"                      > .secrets/DB_NAME
echo "<пользователь базы>"             > .secrets/DB_USER
echo "<пароль базы>"                   > .secrets/DB_PASSWORD
echo "<ключ LaTeX API>"                > .secrets/LATEX_API_KEY
chmod 600 .secrets/*

# 4) База и статика
cd public_html
DJANGO_ENV=production ../venv/bin/python manage.py migrate
DJANGO_ENV=production ../venv/bin/python manage.py seed_topics
DJANGO_ENV=production ../venv/bin/python manage.py collectstatic --noinput
DJANGO_ENV=production ../venv/bin/python manage.py createsuperuser
```

`public_html/wsgi.py` и `public_html/.htaccess` уже в репозитории и сами
вычисляют пути — править их не нужно. Перезапуск приложения: `touch public_html/wsgi.py`.

Проверка: открыть сайт → страница логина; `/admin/` → войти суперпользователем;
создать учителя (пользователь + профиль с ролью «учитель»).

## 3. Автодеплой

```bash
cp <site>/deploy/auto_pull.sh ~/auto_pull.sh
chmod +x ~/auto_pull.sh
# при необходимости поправить SITE_DIR в начале скрипта
```

В панели Timeweb → «Планировщик» (crontab -e недоступен) добавить задание
каждые 5 минут:

```
/bin/bash /home/c/cs13661/auto_pull.sh
```

Дальше деплой = `git push origin main`. Скрипт сам чистит известные помехи
(конфликтные копии Dropbox, `staticfiles/`, залётный `local_settings.py`),
делает pull, migrate, collectstatic и перезапускает приложение.

ВАЖНО: деплой из GitHub Actions по SSH на Timeweb не работает (соединения
режутся) — не тратить время, использовать только auto-pull с сервера.

## 4. HTTPS и безопасность

1. Панель Timeweb → SSL → выпустить Let's Encrypt для домена, включить
  перенаправление HTTP→HTTPS.
2. В `core/settings.py` при `DJANGO_ENV=production` уже включены
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS`.
3. Медиа (фото решений, PDF) лежат в `<site>/media/` — вне `public_html`,
  наружу отдаются только через Django с проверкой прав.



## 5. Известные грабли (из опыта chgkmsu)


| Проблема                                         | Решение                                                                                       |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Холодный старт ~1 с на запрос (CGI-WSGI)         | Норма для тарифа; кэш PDF уже есть; при желании спросить поддержку о Passenger                |
| `git pull` падает из-за untracked `staticfiles/` | `auto_pull.sh` удаляет их перед pull; каталог в `.gitignore`                                  |
| Конфликтные копии Dropbox в рабочей папке        | Прод не синхронизировать Dropbox'ом; скрипт чистит `* (Конфликтующая копия*`                  |
| Сайт 500 при `DEBUG=False` без секретов          | Создавать `.secrets/` до деплоя (шаг 2.3)                                                     |
| Статика админки 404                              | `collectstatic` + rewrite `/static/` → `staticfiles/` в `.htaccess`                           |
| 401 от LaTeX API                                 | Сверить ключ в `.secrets/LATEX_API_KEY` и `/opt/latex-api/config.py`, перезапустить сервис    |
| PDF с `2/??` вместо `2/2`                        | Патч двух прогонов на API (п. 1.5); Django-кэш хранит уже готовый PDF — после патча перегенерировать |
| Ошибка компиляции листка                         | Страница ошибки показывает лог; `/worksheets/<id>/tex/` отдаёт исходник для локальной отладки |
| Письма/уведомления                               | Не используются; пароли учеников учитель передаёт лично                                       |
| Стили «не применились» после правки шаблона      | Локально `make build-css` и закоммитить `public_html/static/css/app.css` (на сервере CSS не собирается) |
| Забыли `app.css` в коммите                       | На проде нет новых utility-классов; всегда коммитить `input.css` + `app.css` вместе           |


## 6. Стили на сервере

Node на Timeweb **не нужен**: `public_html/static/css/app.css` собирается
локально и лежит в git, серверу достаточно обычного `collectstatic` в
`auto_pull.sh`. Как собирать и что коммитить — в
[docs/PIPELINE.md](../docs/PIPELINE.md).

