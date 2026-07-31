#!/bin/bash
###############################################################################
# Автодеплой egormath-web через git pull (по образцу chgkmsu).
#
# Запускается на сервере Timeweb по cron (панель → «Планировщик», каждые 5 мин):
#   /bin/bash $HOME/auto_pull.sh
#
# Перед первым запуском поправьте SITE_DIR под фактический путь сайта.
###############################################################################

SITE_DIR="$HOME/egormath"                 # корень сайта = git-репозиторий
DJANGO_DIR="$SITE_DIR/public_html"
VENV_DIR="$SITE_DIR/venv"
LOG_FILE="$SITE_DIR/deploy.log"
LOCK_FILE="$SITE_DIR/deploy.lock"
BRANCH="main"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Не запускаемся параллельно
if [ -f "$LOCK_FILE" ]; then
    # Протухший lock (>30 мин) удаляем
    if [ -n "$(find "$LOCK_FILE" -mmin +30 2>/dev/null)" ]; then
        log "Stale lock removed"
        rm -f "$LOCK_FILE"
    else
        exit 0
    fi
fi
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd "$SITE_DIR" || { log "ERROR: no $SITE_DIR"; exit 1; }

git fetch origin "$BRANCH" >>"$LOG_FILE" 2>&1

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

log "===== New commits, deploying ====="
git log HEAD.."origin/$BRANCH" --oneline | tee -a "$LOG_FILE"

# Известные грабли Timeweb/Dropbox: конфликтные копии и хвосты collectstatic
find "$SITE_DIR" -type f -name "* (Конфликтующая копия*" -delete 2>/dev/null
rm -f "$DJANGO_DIR/core/local_settings.py"
rm -rf "$DJANGO_DIR/staticfiles"

# Незавершённые merge и локальный мусор
git merge --abort >>"$LOG_FILE" 2>&1 || true
git reset --hard HEAD >>"$LOG_FILE" 2>&1
git clean -fd >>"$LOG_FILE" 2>&1 || true

if ! git pull origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    log "ERROR: git pull failed"
    exit 1
fi

# Зависимости
. "$VENV_DIR/bin/activate" || export PATH="$VENV_DIR/bin:$PATH"
pip install -q -r "$SITE_DIR/requirements.txt" >>"$LOG_FILE" 2>&1

cd "$DJANGO_DIR" || { log "ERROR: no $DJANGO_DIR"; exit 1; }
export DJANGO_ENV=production

log "migrate..."
python manage.py migrate --noinput >>"$LOG_FILE" 2>&1

log "collectstatic..."
python manage.py collectstatic --noinput >>"$LOG_FILE" 2>&1

# Перезапуск приложения (CGI-WSGI перечитывает код после touch)
touch "$DJANGO_DIR/wsgi.py"

# Обновляем сам скрипт в $HOME, если изменился в репозитории
if ! cmp -s "$SITE_DIR/deploy/auto_pull.sh" "$HOME/auto_pull.sh"; then
    cp "$SITE_DIR/deploy/auto_pull.sh" "$HOME/auto_pull.sh"
    chmod +x "$HOME/auto_pull.sh"
    log "auto_pull.sh updated"
fi

log "===== Deploy OK ====="
