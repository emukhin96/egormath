#!/usr/bin/env bash
# Локальный стенд со слепком прода: ночной дамп базы и media с VPS → MySQL на
# Mac, отдельный worktree .worktrees/stage с веткой для просмотра. Прод не
# меняется: с сервера только читаем (при --fresh запускаем backup.sh).
# Подробности — docs/PIPELINE.md, «Локальный стенд со слепком прода».
#
#   tools/stage.sh                 # последний дамп + media, worktree на ветке preview (или main)
#   tools/stage.sh --fresh         # сначала снять новый дамп на сервере
#   tools/stage.sh --no-media      # без rsync media
#   tools/stage.sh --branch ui/x   # ветка для worktree
#   tools/stage.sh --run           # после подготовки запустить runserver
#
# Переменные окружения (значения по умолчанию):
#   STAGE_HOST=chemolymp-demo      SSH-хост из ~/.ssh/config
#   STAGE_APP_DIR=/opt/egormath    каталог стека на сервере (данные в $APP_DIR/data)
#   STAGE_DB=egormath_stage        локальная база; пересоздаётся при каждом запуске
#   STAGE_MYSQL="mysql -uroot"     клиент для заливки дампа
#   STAGE_SOCKET=/tmp/mysql.sock   сокет локального MySQL (Homebrew)
#   STAGE_PORT=8003                порт runserver
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${STAGE_HOST:-chemolymp-demo}"
APP_DIR="${STAGE_APP_DIR:-/opt/egormath}"
DB="${STAGE_DB:-egormath_stage}"
MYSQL="${STAGE_MYSQL:-mysql -uroot}"
SOCKET="${STAGE_SOCKET:-/tmp/mysql.sock}"
PORT="${STAGE_PORT:-8003}"
STAGE_DIR="$ROOT/.worktrees/stage"
DUMPS="$ROOT/.stage"
PYTHON="$ROOT/venv/bin/python"

FRESH=0; MEDIA=1; RUN=0; BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fresh) FRESH=1 ;;
    --no-media) MEDIA=0 ;;
    --run) RUN=1 ;;
    --branch) BRANCH="${2:?--branch <ветка>}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "!! $*" >&2; exit 1; }
[ -x "$PYTHON" ] || die "нет $PYTHON — создайте venv (README, «Локальный запуск»)"
command -v mysql >/dev/null || die "нет клиента mysql (brew install mysql)"
[ -S "$SOCKET" ] || die "MySQL не запущен: нет сокета $SOCKET (brew services start mysql)"
$MYSQL -e 'SELECT 1' >/dev/null 2>&1 || die "не подключиться: $MYSQL (STAGE_MYSQL=\"mysql -uroot -p…\")"

# 1. worktree со стендовой веткой
if [ -z "$BRANCH" ]; then
  if git -C "$ROOT" show-ref --verify --quiet refs/heads/preview; then BRANCH=preview; else BRANCH=main; fi
fi
if [ ! -d "$STAGE_DIR" ]; then
  echo "==> worktree $STAGE_DIR ($BRANCH)"
  git -C "$ROOT" worktree add "$STAGE_DIR" "$BRANCH" 2>/dev/null \
    || git -C "$ROOT" worktree add --detach "$STAGE_DIR" "$BRANCH"
else
  echo "==> worktree $STAGE_DIR → $BRANCH"
  git -C "$STAGE_DIR" checkout -q "$BRANCH" 2>/dev/null \
    || git -C "$STAGE_DIR" checkout -q --detach "$BRANCH"
fi
grep -q "DB_ENGINE" "$STAGE_DIR/public_html/core/settings.py" \
  || die "ветка $BRANCH не знает DB_ENGINE (settings.py): нужна ветка с PR «Локальный стенд» или новее"
# Секреты (LATEX_API_KEY, GEMINI_*) — те же, что у рабочей копии.
[ -e "$STAGE_DIR/.secrets" ] || ln -s "$ROOT/.secrets" "$STAGE_DIR/.secrets"
[ -e "$STAGE_DIR/tools/tailwindcss" ] || [ ! -e "$ROOT/tools/tailwindcss" ] \
  || ln -s "$ROOT/tools/tailwindcss" "$STAGE_DIR/tools/tailwindcss"

# 2. дамп базы с сервера
mkdir -p "$DUMPS"
if [ "$FRESH" = 1 ]; then
  echo "==> backup.sh на $HOST"
  ssh "$HOST" "$APP_DIR/deploy/vps/backup.sh" >/dev/null
fi
LATEST="$(ssh "$HOST" "ls -t $APP_DIR/data/backups/db-*.sql.gz 2>/dev/null | head -n 1")"
[ -n "$LATEST" ] || die "на $HOST нет дампов db-*.sql.gz в $APP_DIR/data/backups"
DUMP="$DUMPS/$(basename "$LATEST")"
if [ ! -s "$DUMP" ]; then
  echo "==> $LATEST → .stage/"
  scp -q "$HOST:$LATEST" "$DUMP"
else
  echo "==> дамп уже скачан: $(basename "$DUMP")"
fi

# 3. локальная база: пересоздать и залить
echo "==> MySQL: пересоздать $DB и залить дамп"
$MYSQL -e "DROP DATABASE IF EXISTS \`$DB\`; CREATE DATABASE \`$DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
gunzip -c "$DUMP" | $MYSQL "$DB"
# Таблицы часовых поясов: без них __date-выборки Django дают NULL.
TZ_CHECK="$($MYSQL -N -e "SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Moscow')")"
if [ "$TZ_CHECK" = "NULL" ]; then
  echo "==> таблицы часовых поясов MySQL"
  mysql_tzinfo_to_sql /usr/share/zoneinfo 2>/dev/null | $MYSQL mysql
fi

# 4. media
if [ "$MEDIA" = 1 ]; then
  echo "==> media → $STAGE_DIR/media/"
  mkdir -p "$STAGE_DIR/media"
  rsync -az --delete "$HOST:$APP_DIR/data/media/" "$STAGE_DIR/media/"
fi

# 5. миграции ветки поверх дампа
STAGE_ENV=(DB_ENGINE=mysql "DB_NAME=$DB" DB_USER=root DB_HOST=localhost "DB_SOCKET=$SOCKET")
echo "==> migrate"
(cd "$STAGE_DIR/public_html" && env "${STAGE_ENV[@]}" "$PYTHON" manage.py migrate --no-input | tail -n 3)

LAN="$(ipconfig getifaddr en0 2>/dev/null || true)"
HOSTS="localhost,127.0.0.1${LAN:+,$LAN}"
cat <<MSG

Стенд готов: $BRANCH ($(git -C "$STAGE_DIR" rev-parse --short HEAD)), база $DB, дамп $(basename "$DUMP").
Запуск (или tools/stage.sh --run):
  cd $STAGE_DIR/public_html && env ${STAGE_ENV[*]} ALLOWED_HOSTS=$HOSTS \\
    $PYTHON manage.py runserver 0.0.0.0:$PORT
  → http://127.0.0.1:$PORT${LAN:+  (с телефона: http://$LAN:$PORT)}
Вход — своим обычным логином и паролем (хэши из дампа).
MSG
if [ "$RUN" = 1 ]; then
  cd "$STAGE_DIR/public_html"
  exec env "${STAGE_ENV[@]}" "ALLOWED_HOSTS=$HOSTS" "$PYTHON" manage.py runserver "0.0.0.0:$PORT"
fi
