# Деплой egormath-web на Timeweb

Схема повторяет проверенную конфигурацию chgkmsu: shared-хостинг Timeweb
(`vh438.timeweb.ru`, аккаунт `cs13661`), Django через CGI-подобный WSGI
(`public_html/wsgi.py` + `.htaccess`), MySQL, автодеплой cron + `auto_pull.sh`.

Ниже `<site>` — имя каталога сайта на сервере (например, `~/egormath`).

## 0. Что нужно подготовить заранее

- [ ] Домен/поддомен, привязанный в панели Timeweb к каталогу `<site>`.
- [ ] MySQL-база в панели Timeweb: имя, пользователь, пароль.
- [ ] Ключ LaTeX API (см. раздел 4) — существующий из chgkmsu или отдельный.
- [ ] Deploy key или доступ к приватному репозиторию GitHub с сервера
      (`ssh-keygen` на сервере → добавить ключ в GitHub → Deploy keys, read-only).

## 1. LaTeX API-сервер (VPS 81.200.147.78, разово)

Пакет `egor.sty` проверен под LuaLaTeX локально — компилируется без ошибок.
На VPS нужно:

1. Положить `egor.sty` в дерево TeX, чтобы его видел `lualatex`:

```bash
mkdir -p /usr/local/texlive/texmf-local/tex/latex/egor
cp egor.sty /usr/local/texlive/texmf-local/tex/latex/egor/
mktexlsr
```

2. Установить шрифты CMU (пакет `cm-unicode` в TeX Live обычно уже есть —
   проверить: `kpsewhich cmunrm.otf`). Для `font=school` положить SchoolBookC
   и TextBookC в `/opt/latex-api/fonts/` или `/usr/local/share/fonts` и
   выполнить `fc-cache -f`.

3. Построить базу шрифтов luaotfload под пользователем, от которого работает
   API (иначе первый запрос упадёт с «CMU Serif cannot be found»):

```bash
sudo -u <api-user> luaotfload-tool --update
```

4. Проверить, что API компилирует **в два прогона** (нужно для
   `\pageref{LastPage}` в колонтитулах egor). Если прогон один — номер
   страниц «1 из ??»; поправить сервис (второй вызов lualatex).

5. Проверка end-to-end: `POST /api/v1/compile-latex` с минимальным документом
   на `egor` (см. `worksheets/latex.py`, функция `worksheet_to_tex`).

Возможные проблемы:
- `no writeable cache path` от luaotfload — у пользователя API нет прав на
  `TEXMFVAR`; создать каталог кэша и дать права, не переопределять TEXMFVAR
  на нестандартный путь.
- 401 — рассинхрон ключа: одно значение в `<site>/.secrets/LATEX_API_KEY`
  и в `/opt/latex-api/config.py`, после правки перезапустить `latex-api`.

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
вычисляют пути — править их не нужно. Перезапуск приложения: `touch
public_html/wsgi.py`.

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

| Проблема | Решение |
|---|---|
| Холодный старт ~1 с на запрос (CGI-WSGI) | Норма для тарифа; кэш PDF уже есть; при желании спросить поддержку о Passenger |
| `git pull` падает из-за untracked `staticfiles/` | `auto_pull.sh` удаляет их перед pull; каталог в `.gitignore` |
| Конфликтные копии Dropbox в рабочей папке | Прод не синхронизировать Dropbox'ом; скрипт чистит `* (Конфликтующая копия*` |
| Сайт 500 при `DEBUG=False` без секретов | Создавать `.secrets/` до деплоя (шаг 2.3) |
| Статика админки 404 | `collectstatic` + rewrite `/static/` → `staticfiles/` в `.htaccess` |
| 401 от LaTeX API | Сверить ключ в `.secrets/LATEX_API_KEY` и `/opt/latex-api/config.py`, перезапустить сервис |
| PDF с «стр. 1 из ??» | На API включить второй прогон lualatex |
| Ошибка компиляции листка | Страница ошибки показывает лог; `/worksheets/<id>/tex/` отдаёт исходник для локальной отладки |
| Письма/уведомления | Не используются; пароли учеников учитель передаёт лично |
