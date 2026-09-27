#!/usr/bin/env bash
# Бэкап egormath: дамп MySQL + архив media в $DATA_DIR/backups,
# старше RETENTION_DAYS удаляются; при BACKUP_RCLONE_REMOTE — копия в S3.
# Запускается из cron (crontab.example) и из deploy.sh перед миграциями.
# Пароль — через MYSQL_PWD, а не -p: без предупреждения в логе и не виден в ps.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
RETENTION_DAYS="$(env_get RETENTION_DAYS)"; RETENTION_DAYS="${RETENTION_DAYS:-14}"
REMOTE="$(env_get BACKUP_RCLONE_REMOTE)"
DIR="$DATA_DIR/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR"

echo "==> mysqldump -> backups/db-$STAMP.sql.gz"
$COMPOSE exec -T egormath-db sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --single-transaction --routines --no-tablespaces --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' \
  | gzip > "$DIR/db-$STAMP.sql.gz.part"
mv "$DIR/db-$STAMP.sql.gz.part" "$DIR/db-$STAMP.sql.gz"

echo "==> media -> backups/media-$STAMP.tar.gz"
tar -czf "$DIR/media-$STAMP.tar.gz" -C "$DATA_DIR" media

find "$DIR" -type f -mtime +"$RETENTION_DAYS" -delete
ls -lh "$DIR" | tail -n 4

if [ -n "$REMOTE" ] && command -v rclone >/dev/null 2>&1; then
  echo "==> rclone -> $REMOTE"
  rclone copy "$DIR" "$REMOTE" --max-age 25h
  rclone delete "$REMOTE" --min-age "${RETENTION_DAYS}d" || true
fi
