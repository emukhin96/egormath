#!/bin/bash
###############################################################################
# Ручной деплой egormath-web на Timeweb.
#
# Только по SSH, не из cron и не из GitHub Actions:
#   ssh cs13661@vh426.timeweb.ru
#   /home/c/cs13661/egormath/deploy/deploy.sh
#
# Не копирует себя в $HOME/auto_pull.sh — там cron chgkmsu.
###############################################################################

SITE_DIR="/home/c/cs13661/egormath"
DJANGO_DIR="$SITE_DIR/public_html"
VENV_DIR="$SITE_DIR/venv"
LOG_FILE="$SITE_DIR/deploy.log"
LOCK_FILE="$SITE_DIR/deploy.lock"
BRANCH="main"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

if [ -f "$LOCK_FILE" ]; then
    if [ -n "$(find "$LOCK_FILE" -mmin +30 2>/dev/null)" ]; then
        log "Stale lock removed"
        rm -f "$LOCK_FILE"
    else
        log "ERROR: deploy already running ($LOCK_FILE)"
        exit 1
    fi
fi
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd "$SITE_DIR" || { log "ERROR: no $SITE_DIR"; exit 1; }

log "===== Deploy start ====="
git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE"

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date ($(git rev-parse --short HEAD))"
else
    log "New commits:"
    git log HEAD.."origin/$BRANCH" --oneline | tee -a "$LOG_FILE"
fi

find "$SITE_DIR" -type f -name "* (Конфликтующая копия*" -delete 2>/dev/null
rm -f "$DJANGO_DIR/core/local_settings.py"
rm -rf "$DJANGO_DIR/staticfiles"

git merge --abort >>"$LOG_FILE" 2>&1 || true
git reset --hard HEAD >>"$LOG_FILE" 2>&1
git clean -fd >>"$LOG_FILE" 2>&1 || true

if [ "$LOCAL" != "$REMOTE" ]; then
    if ! git pull origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
        log "ERROR: git pull failed"
        exit 1
    fi
fi

. "$VENV_DIR/bin/activate" || export PATH="$VENV_DIR/bin:$PATH"
log "pip install..."
pip install -q -r "$SITE_DIR/requirements.txt" >>"$LOG_FILE" 2>&1

cd "$DJANGO_DIR" || { log "ERROR: no $DJANGO_DIR"; exit 1; }
export DJANGO_ENV=production

log "check --deploy..."
if ! python manage.py check --deploy --fail-level ERROR >>"$LOG_FILE" 2>&1; then
    log "ERROR: manage.py check --deploy failed"
    exit 1
fi

log "migrate..."
if ! python manage.py migrate --noinput >>"$LOG_FILE" 2>&1; then
    log "ERROR: migrate failed"
    exit 1
fi

log "seed_rubricator..."
if ! python manage.py seed_rubricator >>"$LOG_FILE" 2>&1; then
    log "ERROR: seed_rubricator failed"
    exit 1
fi

# app.css не в git — собираем до collectstatic, иначе сайт уйдёт без стилей
log "build-css..."
if ! make -C "$SITE_DIR" build-css >>"$LOG_FILE" 2>&1; then
    log "ERROR: make build-css failed"
    exit 1
fi

log "collectstatic..."
if ! python manage.py collectstatic --noinput >>"$LOG_FILE" 2>&1; then
    log "ERROR: collectstatic failed"
    exit 1
fi

touch "$DJANGO_DIR/wsgi.py"
log "===== Deploy OK ($(git rev-parse --short HEAD)) ====="
