#!/usr/bin/env bash
# Залить дамп MySQL (.sql или .sql.gz) в базу egormath вместо текущей.
#   deploy/vps/import-db.sh egormath-20260927.sql.gz [--yes] [--no-backup]
# Для переезда с Timeweb (репетиция и переключение) и восстановления из бэкапа
# (restore.sh). Текущая база перед заливкой сохраняется через backup.sh;
# если свежий дамп не появился — заливка отменяется. --no-backup — осознанно
# продолжить без бэкапа (например, база заведомо мусорная).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
DUMP="${1:?usage: import-db.sh <dump.sql[.gz]> [--yes] [--no-backup]}"
[ -r "$DUMP" ] || { echo "Нет файла $DUMP" >&2; exit 1; }
YES=0; NO_BACKUP=0
shift
for ARG in "$@"; do
  case "$ARG" in
    --yes) YES=1 ;;
    --no-backup) NO_BACKUP=1 ;;
    *) echo "Неизвестный аргумент: $ARG" >&2; exit 2 ;;
  esac
done
if [ "$YES" != 1 ]; then
  read -r -p "Стереть базу egormath и залить $DUMP? [yes/N] " ANSWER
  [ "$ANSWER" = "yes" ] || { echo "Отменено."; exit 1; }
fi

$COMPOSE up -d --wait egormath-db
# Бэкап текущей базы — по её состоянию, а не по состоянию web: если в базе
# есть таблицы, сохраняем её и при остановленном или упавшем web.
# Не узнали состояние (пароль root, mysql ещё не принимает соединения) —
# останавливаемся: без ответа «0» пропускать бэкап перед DROP DATABASE нельзя.
TABLES="$($COMPOSE exec -T egormath-db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = \"$MYSQL_DATABASE\""')" \
  || { echo "!! не удалось запросить состояние базы — бэкап не снят, заливка отменена" >&2; exit 1; }
TABLES="${TABLES%$'\r'}"
case "$TABLES" in
  ''|*[!0-9]*) echo "!! неожиданный ответ MySQL о числе таблиц: '$TABLES' — заливка отменена" >&2; exit 1 ;;
esac
if [ "$TABLES" != "0" ] && [ "$NO_BACKUP" = 1 ]; then
  echo "!! --no-backup: база не пуста ($TABLES таблиц), бэкап перед заливкой пропущен по явному запросу"
elif [ "$TABLES" != "0" ]; then
  # Критерий — появился ли свежий дамп базы, а не код выхода backup.sh:
  # тот падает и по причинам, не связанным с дампом (rclone, секреты).
  BACKUPS="$DATA_DIR/backups"
  BEFORE="$(ls -t "$BACKUPS"/db-*.sql.gz 2>/dev/null | head -n 1 || true)"
  "$(dirname "$0")/backup.sh" || echo "!! backup.sh завершился с ошибкой — проверяю, снят ли дамп базы"
  AFTER="$(ls -t "$BACKUPS"/db-*.sql.gz 2>/dev/null | head -n 1 || true)"
  if [ -z "$AFTER" ] || [ "$AFTER" = "$BEFORE" ] || ! gzip -t "$AFTER" 2>/dev/null; then
    echo "!! свежий дамп текущей базы не появился в $BACKUPS — заливка отменена (осознанно без бэкапа: --no-backup)" >&2
    exit 1
  fi
  echo "==> бэкап текущей базы: $(basename "$AFTER")"
fi
# На свежем сервере (restore.sh) контейнера web ещё нет — тогда не трогаем.
WEB_RUNNING=0
if $COMPOSE ps --status running --services 2>/dev/null | grep -q '^egormath-web$'; then
  WEB_RUNNING=1
  $COMPOSE stop egormath-web
fi

echo "==> Пересоздание базы"
$COMPOSE exec -T egormath-db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "
  DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`;
  CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  GRANT ALL ON \`$MYSQL_DATABASE\`.* TO \"$MYSQL_USER\"@\"%\";"'

echo "==> Заливка $DUMP"
START=$(date +%s)
case "$DUMP" in
  *.gz) gunzip -c "$DUMP" ;;
  *) cat "$DUMP" ;;
esac | $COMPOSE exec -T egormath-db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"'
echo "==> Готово за $(( $(date +%s) - START )) с"

# Таблицы часовых поясов: в свежем контейнере mysql:8.0 они пустые, и
# __date-выборки Django (CONVERT_TZ) дают NULL. В дамп базы egormath они
# не входят — грузим из zoneinfo самого контейнера.
TZ_CHECK="$($COMPOSE exec -T egormath-db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT CONVERT_TZ(\"2026-01-01 00:00:00\",\"UTC\",\"Europe/Moscow\")"')"
if [ "${TZ_CHECK%$'\r'}" = "NULL" ]; then
  echo "==> Таблицы часовых поясов MySQL пусты — загружаю"
  # export: пароль нужен второй команде конвейера (mysql), а не mysql_tzinfo_to_sql
  $COMPOSE exec -T egormath-db sh -c 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; mysql_tzinfo_to_sql /usr/share/zoneinfo 2>/dev/null | mysql -uroot mysql'
fi

echo "==> Число строк в ключевых таблицах (сверить с источником дампа)"
$COMPOSE exec -T egormath-db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "
  SELECT table_name, table_rows FROM information_schema.tables
  WHERE table_schema = DATABASE() ORDER BY table_rows DESC LIMIT 15;
  SELECT CONVERT_TZ(NOW(), \"UTC\", \"Europe/Moscow\") AS tz_check;"'

# Не список «&& …; exit 0»: ошибка запуска web должна стать кодом выхода скрипта.
if [ "$WEB_RUNNING" = 1 ]; then
  $COMPOSE up -d egormath-web
fi
