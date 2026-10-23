# Образ egormath для VPS (стек deploy/vps/compose.yaml).
# Python 3.12 — как в CI. Код лежит в образе, данные
# (media, секреты, файлы-версии live/, staticfiles/) монтируются снаружи.

# app.css не хранится в git — собираем его здесь тем же Tailwind standalone,
# что и `make build-css` (версия — TW_VERSION в Makefile). Шаблоны и JS
# копируются в те же пути, что в репозитории: input.css ищет их через @source.
FROM debian:bookworm-slim AS css
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Makefile .
# Tailwind (~110 МБ) — отдельным слоем до копирования стилей и шаблонов:
# качается заново только при правке Makefile, а не на каждом деплое.
RUN make ensure-tailwind
COPY public_html/static public_html/static
COPY public_html/templates public_html/templates
RUN make build-css

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_ENV=production

# UID пользователя приложения = UID владельца /opt/egormath на сервере
# (deploy), чтобы примонтированные каталоги были доступны на запись без chown.
ARG APP_UID=1000
RUN useradd --uid "${APP_UID}" --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
COPY --from=css --chown=app:app /src/public_html/static/css/app.css public_html/static/css/app.css

USER app
WORKDIR /app/public_html
EXPOSE 8000
CMD ["gunicorn", "-c", "/app/deploy/vps/gunicorn.conf.py", "core.wsgi:application"]
