# egormath-web

Веб-система для создания листков с задачами по математике, выдачи и проверки
домашних заданий и самостоятельных работ.

- Учитель: база задач, конструктор листков, генерация PDF (LuaLaTeX + пакет
  `egor` через удалённый LaTeX API), назначение заданий ученикам, проверка
  ответов с отметками и комментариями.
- Ученик: назначенные задания, отправка кратких ответов (текст / число /
  промежуток / фото решения), просмотр комментариев учителя.
- Публичные ссылки на листок (просмотр и PDF без ответов, без входа на сайт).

## Стек

Django 4.2 (Python 3.10), SQLite локально / MySQL на проде (Timeweb shared),
PDF — внешний LaTeX API-сервер (LuaLaTeX), KaTeX для формул на сайте.
Стили — Tailwind CSS v4 (standalone CLI): исходник
`public_html/static/css/input.css`, собранный артефакт
`public_html/static/css/app.css` (коммитится в git).

### Сборка CSS

На сервере Node **не нужен**. После изменений в `input.css` или новых
utility-классов в шаблонах локально:

```bash
make build-css   # скачает CLI в tools/ при необходимости
make check       # сборка + тесты + проверка, что app.css закоммичен свежим
```

Правило: **новый utility в шаблоне → `make build-css` → закоммитить `app.css`**.
Повторяющиеся куски лучше выносить в `@layer components` в `input.css`,
а не копировать длинные class-строки. Подробности — в
[docs/PIPELINE.md](docs/PIPELINE.md).

## Локальный запуск

```bash
python3.10 -m venv venv
./venv/bin/pip install -r requirements.txt
cd public_html
../venv/bin/python manage.py migrate
../venv/bin/python manage.py seed_topics       # стартовый рубрикатор тем
../venv/bin/python manage.py createsuperuser
../venv/bin/python manage.py runserver
```

Учителя создаются админом в админке (`/admin/`, профиль с ролью «учитель»),
учеников создаёт учитель в своём кабинете.

Для генерации PDF нужен ключ API: файл `.secrets/LATEX_API_KEY` в корне
проекта (или переменная окружения).

## Разработка и деплой

Процесс работы (локальный запуск, ветки, PR-ревью, CI) —
[docs/PIPELINE.md](docs/PIPELINE.md).

Деплой на Timeweb отложен; инструкция сохранена как справочная:
[deploy/DEPLOY.md](deploy/DEPLOY.md).

## Структура

- `public_html/` — Django-проект (на Timeweb это DOCUMENT_ROOT)
  - `core/` — настройки, урлы
  - `accounts/` — пользователи, роли, дашборды
  - `problems/` — база задач, темы, теги, источники
  - `worksheets/` — листки, генерация .tex/PDF, публичные ссылки
  - `assignments/` — назначения, ответы учеников, проверка
- `deploy/` — файлы для деплоя на Timeweb (wsgi, .htaccess, auto_pull)
- `docs/` — процесс разработки (`PIPELINE.md`)
- `media/` (не в git) — фото решений и кэш PDF, вне public_html
- `.secrets/` (не в git) — секреты продакшена
