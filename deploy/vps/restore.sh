#!/usr/bin/env bash
###############################################################################
# Восстановление стека egormath из бэкапа — после потери сервера или для
# отката на ночной слепок. Порядок и подготовка нового сервера —
# deploy/VPS.md, «Восстановление после потери сервера».
#
#   deploy/vps/restore.sh [--stamp YYYYMMDD-HHMMSS] [--from <откуда>] [--yes] [--no-deploy]
#
#   --from   каталог с файлами бэкапа или rclone-remote (по умолчанию
#            BACKUP_RCLONE_REMOTE из .env, а если он пуст — data/backups)
#   --stamp  какой набор брать (по умолчанию — самый свежий дамп базы)
#   --yes    не спрашивать подтверждений
#   --no-deploy  не запускать deploy.sh в конце
#
# Набор бэкапа за одну отметку времени (backup.sh):
#   db-<stamp>.sql.gz  media-<stamp>.tar.gz  var-<stamp>.tar.gz
#   secrets-<stamp>.tar.gz.enc  (data/secrets, .env, crontab, rclone.conf;
#   расшифровывается паролем BACKUP_SECRETS_PASSPHRASE из .env)
#
# Что делает: скачивает набор → секреты в data/secrets (если там пусто) →
# import-db.sh → media и var из архивов → deploy.sh (образ, миграции,
# collectstatic, контейнеры, Caddy).
###############################################################################
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"
cd "$APP_DIR"

STAMP=""; FROM=""; YES=0; DEPLOY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --stamp) STAMP="${2:?--stamp YYYYMMDD-HHMMSS}"; shift ;;
    --from) FROM="${2:?--from <каталог|remote:bucket>}"; shift ;;
    --yes) YES=1 ;;
    --no-deploy) DEPLOY=0 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "!! $*" >&2; exit 1; }
confirm() {
  [ "$YES" = 1 ] && return 0
  read -r -p "$1 [yes/N] " ANSWER; [ "$ANSWER" = "yes" ]
}

DIR="$DATA_DIR/backups"
mkdir -p "$DIR" "$DATA_DIR"/{secrets,media,var,live,cache,staticfiles,mysql,logs}
[ -n "$FROM" ] || FROM="$(env_get BACKUP_RCLONE_REMOTE)"
[ -n "$FROM" ] || FROM="$DIR"

# 1. Набор файлов: из S3 (rclone) или из каталога
if [ -d "$FROM" ]; then
  SRC_DIR="$FROM"
  [ -n "$STAMP" ] || STAMP="$(ls "$SRC_DIR"/db-*.sql.gz 2>/dev/null | sed -E 's/.*db-([0-9]{8}-[0-9]{6})\.sql\.gz/\1/' | sort | tail -n 1)"
  [ -n "$STAMP" ] || die "в $SRC_DIR нет дампов db-*.sql.gz"
  if [ "$SRC_DIR" != "$DIR" ]; then
    cp "$SRC_DIR"/*-"$STAMP".* "$DIR/"
  fi
else
  command -v rclone >/dev/null || die "нет rclone: apt-get install -y rclone, затем rclone config (deploy/VPS.md)"
  rclone lsd "$FROM" >/dev/null 2>&1 || die "rclone не видит $FROM — проверьте rclone config и BACKUP_RCLONE_REMOTE"
  [ -n "$STAMP" ] || STAMP="$(rclone lsf "$FROM" --include 'db-*.sql.gz' | sed -E 's/db-([0-9]{8}-[0-9]{6})\.sql\.gz/\1/' | sort | tail -n 1)"
  [ -n "$STAMP" ] || die "в $FROM нет дампов db-*.sql.gz"
  echo "==> $FROM -> $DIR: набор $STAMP"
  rclone copy "$FROM" "$DIR" --include "*-$STAMP.*"
fi
DB="$DIR/db-$STAMP.sql.gz"; MEDIA="$DIR/media-$STAMP.tar.gz"
VAR="$DIR/var-$STAMP.tar.gz"; SECRETS="$DIR/secrets-$STAMP.tar.gz.enc"
[ -r "$DB" ] || die "нет $DB"
echo "==> Набор $STAMP:"; ls -lh "$DIR"/*-"$STAMP".*
gzip -t "$DB" || die "дамп $DB повреждён"
confirm "Восстановить стек в $APP_DIR из набора $STAMP (база будет заменена)?" || { echo "Отменено."; exit 1; }

# 2. Секреты
if [ -r "$SECRETS" ]; then
  PASSPHRASE="${BACKUP_SECRETS_PASSPHRASE:-$(env_get BACKUP_SECRETS_PASSPHRASE)}"
  if [ -z "$PASSPHRASE" ]; then
    echo "!! BACKUP_SECRETS_PASSPHRASE пуст в $ENV_FILE — архив секретов $SECRETS не расшифрован"
  else
    UNPACKED="$DATA_DIR/restored-secrets-$STAMP"
    rm -rf "$UNPACKED"; mkdir -p "$UNPACKED"; chmod 700 "$UNPACKED"
    BACKUP_PASS="$PASSPHRASE" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
      -pass env:BACKUP_PASS -in "$SECRETS" | tar -xzf - -C "$UNPACKED" \
      || die "не расшифровать $SECRETS: неверный BACKUP_SECRETS_PASSPHRASE?"
    if [ -z "$(ls -A "$DATA_DIR/secrets")" ]; then
      echo "==> data/secrets пуст — заполняю из архива"
      cp -a "$UNPACKED/secrets/." "$DATA_DIR/secrets/"
      chmod 700 "$DATA_DIR/secrets"; chmod 600 "$DATA_DIR/secrets"/*
    else
      echo "==> data/secrets не пуст — оставляю как есть; архивные файлы в $UNPACKED/secrets"
    fi
    if [ -r "$UNPACKED/rclone.conf" ] && [ ! -r "$HOME/.config/rclone/rclone.conf" ]; then
      mkdir -p "$HOME/.config/rclone"; cp "$UNPACKED/rclone.conf" "$HOME/.config/rclone/rclone.conf"
      chmod 600 "$HOME/.config/rclone/rclone.conf"; echo "==> rclone.conf восстановлен"
    fi
    echo "==> Сверить вручную и удалить $UNPACKED:"
    echo "    diff $UNPACKED/env $ENV_FILE        # старый .env (пароли MySQL могут отличаться — это нормально)"
    echo "    diff $UNPACKED/crontab <(crontab -l)   # затем crontab -e (deploy/vps/crontab.example)"
  fi
else
  echo "!! в наборе нет secrets-$STAMP.tar.gz.enc — секреты перенесите вручную (deploy/VPS.md)"
fi
[ -s "$DATA_DIR/secrets/DJANGO_SECRET_KEY" ] || echo "!! нет data/secrets/DJANGO_SECRET_KEY — deploy.sh упадёт на check --deploy"

# 3. База
"$APP_DIR/deploy/vps/import-db.sh" "$DB" --yes

# 4. media и var
unpack() {  # unpack <архив> <каталог в data/>
  local archive="$1" name="$2"
  [ -r "$archive" ] || { echo "!! нет $archive — $name не восстановлен"; return 0; }
  if [ -n "$(ls -A "$DATA_DIR/$name" 2>/dev/null)" ]; then
    confirm "data/$name не пуст — дописать поверх файлы из $(basename "$archive")?" || { echo "    пропускаю $name"; return 0; }
  fi
  echo "==> $(basename "$archive") -> data/$name"
  tar -xzf "$archive" -C "$DATA_DIR"
}
unpack "$MEDIA" media
unpack "$VAR" var

# 5. Код, образ, миграции, контейнеры, Caddy
if [ "$DEPLOY" = 1 ]; then
  echo "==> deploy.sh"
  "$APP_DIR/deploy/vps/deploy.sh"
else
  echo "==> Осталось: $APP_DIR/deploy/vps/deploy.sh"
fi
echo "===== Restore $STAMP done ====="
