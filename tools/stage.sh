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
#   tools/stage.sh --lan           # слушать 0.0.0.0 и пустить LAN-IP Mac в ALLOWED_HOSTS
#                                  # (стенд с прод-данными и DEBUG — только в доверенной сети)
#
# Переменные окружения (значения по умолчанию):
#   STAGE_HOST=chemolymp-demo      SSH-хост из ~/.ssh/config
#   STAGE_APP_DIR=/opt/egormath    каталог стека на сервере (данные в $APP_DIR/data)
#   STAGE_DB=egormath_stage        локальная база; пересоздаётся при каждом запуске
#   STAGE_DB_USER=root             пользователь MySQL для заливки дампа и для Django
#   STAGE_DB_PASSWORD=             его пароль (пусто — без пароля, как у Homebrew root);
#                                  клиенту mysql уходит через MYSQL_PWD, в командах и выводе не показывается
#   STAGE_SOCKET=/tmp/mysql.sock   сокет локального MySQL (Homebrew); через него идут и заливка, и Django
#   (клиент mysql для заливки собирается из этих трёх переменных — отдельно не переопределяется,
#    чтобы дамп и Django не разъехались по серверам или пользователям)
#   STAGE_PORT=8003                порт runserver
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${STAGE_HOST:-chemolymp-demo}"
APP_DIR="${STAGE_APP_DIR:-/opt/egormath}"
DB="${STAGE_DB:-egormath_stage}"
DB_USER="${STAGE_DB_USER:-root}"
DB_PASSWORD="${STAGE_DB_PASSWORD:-}"
SOCKET="${STAGE_SOCKET:-/tmp/mysql.sock}"
# Клиент — массив слов, а не строка: аргументы с пробелами не разваливаются.
# Тот же пользователь и сокет, что у Django (DB_USER, DB_SOCKET): иначе дамп
# уйдёт в один сервер, а migrate/runserver — в другой. Пароль — через
# MYSQL_PWD, как в deploy/vps/backup.sh: не виден в ps и не печатается.
MYSQL=(mysql "-u$DB_USER" "--socket=$SOCKET")
[ -z "$DB_PASSWORD" ] || export MYSQL_PWD="$DB_PASSWORD"
PORT="${STAGE_PORT:-8003}"
STAGE_DIR="$ROOT/.worktrees/stage"
DUMPS="$ROOT/.stage"
PYTHON="$ROOT/venv/bin/python"

FRESH=0; MEDIA=1; RUN=0; LAN_MODE=0; BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fresh) FRESH=1 ;;
    --no-media) MEDIA=0 ;;
    --run) RUN=1 ;;
    --lan) LAN_MODE=1 ;;
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
"${MYSQL[@]}" -e 'SELECT 1' >/dev/null 2>&1 || die "не подключиться как $DB_USER (STAGE_DB_USER / STAGE_DB_PASSWORD)"

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
# Секреты — только API-ключи из рабочей копии, по одному симлинку: DB_* и
# DJANGO_ENV туда не попадают, база стенда задаётся переменными окружения.
if [ ! -d "$STAGE_DIR/.secrets" ]; then
  mkdir -p "$STAGE_DIR/.secrets"
  for name in LATEX_API_KEY LATEX_API_URL GEMINI_API_KEY GEMINI_API_BASE GEMINI_PROXY_SECRET; do
    [ -e "$ROOT/.secrets/$name" ] && ln -s "$ROOT/.secrets/$name" "$STAGE_DIR/.secrets/$name"
  done
fi
[ -e "$STAGE_DIR/tools/tailwindcss" ] || [ ! -e "$ROOT/tools/tailwindcss" ] \
  || ln -s "$ROOT/tools/tailwindcss" "$STAGE_DIR/tools/tailwindcss"
# Свой SECRET_KEY стенда: dev-ключ по умолчанию лежит в репозитории, а в
# базе — слепок прода. Генерируется один раз в .stage/ (в .gitignore),
# читается settings.py из .secrets стенда как обычный секрет.
mkdir -p "$DUMPS"
if [ ! -s "$DUMPS/DJANGO_SECRET_KEY" ]; then
  "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(50))' > "$DUMPS/DJANGO_SECRET_KEY"
  chmod 600 "$DUMPS/DJANGO_SECRET_KEY"
fi
[ -e "$STAGE_DIR/.secrets/DJANGO_SECRET_KEY" ] \
  || ln -s "$DUMPS/DJANGO_SECRET_KEY" "$STAGE_DIR/.secrets/DJANGO_SECRET_KEY"

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
"${MYSQL[@]}" -e "DROP DATABASE IF EXISTS \`$DB\`; CREATE DATABASE \`$DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
gunzip -c "$DUMP" | "${MYSQL[@]}" "$DB"
# Таблицы часовых поясов: без них __date-выборки Django дают NULL.
TZ_CHECK="$("${MYSQL[@]}" -N -e "SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Moscow')")"
if [ "$TZ_CHECK" = "NULL" ]; then
  echo "==> таблицы часовых поясов MySQL"
  mysql_tzinfo_to_sql /usr/share/zoneinfo 2>/dev/null | "${MYSQL[@]}" mysql
fi

# 4. media
if [ "$MEDIA" = 1 ]; then
  echo "==> media → $STAGE_DIR/media/"
  mkdir -p "$STAGE_DIR/media"
  rsync -az --delete "$HOST:$APP_DIR/data/media/" "$STAGE_DIR/media/"
fi

# 5. миграции ветки поверх дампа
# DB_PASSWORD передаётся всегда, даже пустым: в .secrets стенда DB_* нет,
# поэтому пустое значение означает «без пароля».
STAGE_ENV=(DB_ENGINE=mysql "DB_NAME=$DB" "DB_USER=$DB_USER" "DB_PASSWORD=$DB_PASSWORD" DB_HOST=localhost "DB_SOCKET=$SOCKET")
# Строка для подсказки собирается отдельно: вместо пароля — имя переменной
# (подстановка по образцу читала бы пароль как glob и могла его напечатать).
STAGE_ENV_SHOWN="DB_ENGINE=mysql DB_NAME=$DB DB_USER=$DB_USER DB_PASSWORD=${DB_PASSWORD:+\$STAGE_DB_PASSWORD} DB_HOST=localhost DB_SOCKET=$SOCKET"
echo "==> migrate"
(cd "$STAGE_DIR/public_html" && env "${STAGE_ENV[@]}" "$PYTHON" manage.py migrate --no-input | tail -n 3)

# По умолчанию стенд слушает только 127.0.0.1: в базе персональные данные и
# хэши паролей с прода, а DEBUG включён. Сеть — только явно, флагом --lan.
BIND=127.0.0.1; HOSTS="localhost,127.0.0.1"; LAN=""
if [ "$LAN_MODE" = 1 ]; then
  BIND=0.0.0.0
  LAN="$(ipconfig getifaddr en0 2>/dev/null || true)"
  HOSTS="$HOSTS${LAN:+,$LAN}"
fi
cat <<MSG

Стенд готов: $BRANCH ($(git -C "$STAGE_DIR" rev-parse --short HEAD)), база $DB, дамп $(basename "$DUMP").
Запуск (или tools/stage.sh --run):
  cd $STAGE_DIR/public_html && env $STAGE_ENV_SHOWN ALLOWED_HOSTS=$HOSTS \\
    $PYTHON manage.py runserver $BIND:$PORT
  → http://127.0.0.1:$PORT${LAN:+  (с телефона: http://$LAN:$PORT)}
${DB_PASSWORD:+  STAGE_DB_PASSWORD в этой команде берётся из оболочки — экспортируйте его (export STAGE_DB_PASSWORD=…) или запускайте tools/stage.sh --run.
}Вход — своим обычным логином и паролем (хэши из дампа).
MSG
if [ "$LAN_MODE" = 1 ]; then
  echo "!! --lan: стенд с данными прода и DEBUG=True открыт всей сети${LAN:+ (http://$LAN:$PORT)} — только в доверенной сети." >&2
fi
if [ "$RUN" = 1 ]; then
  cd "$STAGE_DIR/public_html"
  exec env "${STAGE_ENV[@]}" "ALLOWED_HOSTS=$HOSTS" "$PYTHON" manage.py runserver "$BIND:$PORT"
fi
