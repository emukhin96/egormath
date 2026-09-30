#!/usr/bin/env bash
# Залить дамп MySQL (.sql или .sql.gz) в базу egormath вместо текущей.
#   deploy/vps/import-db.sh egormath-20260927.sql.gz [--yes]
# Для переезда с Timeweb (репетиция и переключение) и восстановления из бэкапа
# (restore.sh). Текущая база перед заливкой сохраняется через backup.sh.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
DUMP="${1:?usage: import-db.sh <dump.sql[.gz]> [--yes]}"
[ -r "$DUMP" ] || { echo "Нет файла $DUMP" >&2; exit 1; }
if [ "${2:-}" != "--yes" ]; then
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
if [ "$TABLES" != "0" ]; then
  "$(dirname "$0")/backup.sh" || echo "!! бэкап не удался — продолжаю"
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

[ "$WEB_RUNNING" = 1 ] && $COMPOSE up -d egormath-web
exit 0
