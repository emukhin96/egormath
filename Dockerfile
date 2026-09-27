# Образ egormath для VPS (стек deploy/vps/compose.yaml).
# Python 3.12 — как в CI. Код лежит в образе, данные
# (media, секреты, файлы-версии live/, staticfiles/) монтируются снаружи.
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

USER app
WORKDIR /app/public_html
EXPOSE 8000
CMD ["gunicorn", "-c", "/app/deploy/vps/gunicorn.conf.py", "core.wsgi:application"]
