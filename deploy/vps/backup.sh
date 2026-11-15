#!/usr/bin/env bash
# Бэкап egormath: дамп MySQL, архивы media и var, зашифрованный архив секретов
# (data/secrets, .env, crontab, rclone.conf) в $DATA_DIR/backups. На диске
# наборы старше LOCAL_RETENTION_DAYS (7) удаляются ДО новых архивов; при
# BACKUP_RCLONE_REMOTE — копия в S3, где наборы живут RETENTION_DAYS (14), а
# дампы базы за 1-е число месяца и дампы Timeweb — бессрочно.
# Запускается из cron (crontab.example) и из deploy.sh перед миграциями.
# Восстановление — restore.sh; репетиция на Mac — tools/stage.sh --s3.
# Пароль MySQL — через MYSQL_PWD, а не -p: без предупреждения в логе и не виден в ps.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
RETENTION_DAYS="$(env_get RETENTION_DAYS)"; RETENTION_DAYS="${RETENTION_DAYS:-14}"
LOCAL_RETENTION_DAYS="$(env_get LOCAL_RETENTION_DAYS)"; LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-7}"
# Запас свободного места после архива: иначе бэкап сам заполнит диск и база
# сайта останется без места (15.11.2026 диск дошёл до 100%).
RESERVE_MB="$(env_get BACKUP_RESERVE_MB)"; RESERVE_MB="${RESERVE_MB:-1024}"
REMOTE="$(env_get BACKUP_RCLONE_REMOTE)"
PASSPHRASE="${BACKUP_SECRETS_PASSPHRASE:-$(env_get BACKUP_SECRETS_PASSPHRASE)}"
PING_URL="$(env_get BACKUP_PING_URL)"
DIR="$DATA_DIR/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR"
TMP="$(mktemp -d)"
# Недописанный файл (ошибка, нехватка места) не остаётся на диске.
trap 'rm -rf "$TMP"; rm -f "$DIR"/*-"$STAMP".*.part' EXIT

# Набор старше срока — по отметке времени в имени файла: так набор
# удаляется целиком, а посторонние файлы в каталоге не трогаются.
prune_local() {
  local cutoff name stamp
  cutoff="$(date -d "-$LOCAL_RETENTION_DAYS days" +%Y%m%d-%H%M%S)"
  for name in "$DIR"/*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].*; do
    [ -e "$name" ] || continue
    stamp="$(basename "$name" | sed -E 's/^.*-([0-9]{8}-[0-9]{6})\..*$/\1/')"
    [[ "$stamp" < "$cutoff" ]] && rm -f "$name"
  done
  return 0
}

# Свободно на разделе бэкапов, МБ.
free_mb() { df -Pm "$DIR" | awk 'NR==2 {print $4}'; }

# Архив каталога data/<name> с проверкой места: ~1,2 прошлого архива
# (или размера каталога) плюс запас; иначе архив не создаётся.
archive_dir() {
  local name="$1" out="$DIR/$1-$STAMP.tar.gz" prev need
  prev="$(ls "$DIR/$name"-*.tar.gz 2>/dev/null | sort | tail -n 1 || true)"
  need=$(( RESERVE_MB + ( $( [ -n "$prev" ] && du -m "$prev" | cut -f1 || du -sm "$DATA_DIR/$name" | cut -f1 ) * 12 / 10 ) ))
  if [ "$(free_mb)" -lt "$need" ]; then
    echo "!! мало места для $name: свободно $(free_mb) МБ, нужно ~$need МБ — архив не создан"
    return 1
  fi
  echo "==> $name -> backups/$name-$STAMP.tar.gz"
  tar -czf "$out.part" --exclude='__pycache__' -C "$DATA_DIR" "$name"
  mv "$out.part" "$out"
}

prune_local

echo "==> mysqldump -> backups/db-$STAMP.sql.gz"
$COMPOSE exec -T egormath-db sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --single-transaction --routines --no-tablespaces --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' \
  | gzip > "$DIR/db-$STAMP.sql.gz.part"
mv "$DIR/db-$STAMP.sql.gz.part" "$DIR/db-$STAMP.sql.gz"

archive_dir media

# var/: корпус листков и партии задачников — работа, которой нет в базе,
# пока партия не загружена в каталог.
if [ -d "$DATA_DIR/var" ]; then
  archive_dir var
fi

# Секреты: без DJANGO_SECRET_KEY, ключей API и .env стек с нуля не поднять.
# Архив шифруется openssl (AES-256, PBKDF2) паролем BACKUP_SECRETS_PASSPHRASE;
# копия пароля — на Mac в .secrets/BACKUP_SECRETS_PASSPHRASE (deploy/VPS.md).
if [ -n "$PASSPHRASE" ]; then
  echo "==> secrets -> backups/secrets-$STAMP.tar.gz.enc"
  mkdir -p "$TMP/bundle"
  cp -a "$DATA_DIR/secrets" "$TMP/bundle/secrets"
  cp "$ENV_FILE" "$TMP/bundle/env"
  crontab -l > "$TMP/bundle/crontab" 2>/dev/null || true
  [ -r "$HOME/.config/rclone/rclone.conf" ] && cp "$HOME/.config/rclone/rclone.conf" "$TMP/bundle/rclone.conf"
  tar -czf - -C "$TMP/bundle" . \
    | BACKUP_PASS="$PASSPHRASE" openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
        -pass env:BACKUP_PASS -out "$DIR/secrets-$STAMP.tar.gz.enc.part"
  mv "$DIR/secrets-$STAMP.tar.gz.enc.part" "$DIR/secrets-$STAMP.tar.gz.enc"
  chmod 600 "$DIR/secrets-$STAMP.tar.gz.enc"
else
  echo "!! BACKUP_SECRETS_PASSPHRASE пуст в $ENV_FILE — секреты не бэкапятся (deploy/VPS.md, «Бэкапы»)"
fi

prune_local
ls -lh "$DIR" | tail -n 5
echo "==> диск: свободно $(free_mb) МБ"

if [ -n "$REMOTE" ] && command -v rclone >/dev/null 2>&1; then
  echo "==> rclone -> $REMOTE"
  # Без --max-age: если ночь пропущена, файл всё равно доедет в следующий раз
  # (rclone пропускает уже загруженные по размеру и времени).
  rclone copy "$DIR" "$REMOTE"
  # В S3 бессрочно: дампы базы за 1-е число месяца (~3 МБ) и дампы Timeweb.
  rclone delete "$REMOTE" --min-age "${RETENTION_DAYS}d" \
    --exclude 'db-??????01-*' --exclude 'timeweb*' || true
fi

# Пинг «бэкап прошёл» (Healthchecks.io и т. п.): если строки нет — сервис
# сам присылает тревогу. При ошибке выше скрипт сюда не доходит (set -e).
if [ -n "$PING_URL" ]; then
  curl -fsS -m 10 --retry 3 "$PING_URL" >/dev/null || echo "!! пинг $PING_URL не удался"
fi
