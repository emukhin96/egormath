#!/usr/bin/env bash
# Залить дамп MySQL (.sql или .sql.gz) в базу egormath вместо текущей.
#   deploy/vps/import-db.sh egormath-20260927.sql.gz [--yes]
# Для переезда с Timeweb (репетиция и переключение) и восстановления из бэкапа.
# Текущая база перед заливкой сохраняется через backup.sh.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
DUMP="${1:?usage: import-db.sh <dump.sql[.gz]> [--yes]}"
[ -r "$DUMP" ] || { echo "Нет файла $DUMP" >&2; exit 1; }
if [ "${2:-}" != "--yes" ]; then
  read -r -p "Стереть базу egormath и залить $DUMP? [yes/N] " ANSWER
  [ "$ANSWER" = "yes" ] || { echo "Отменено."; exit 1; }
fi

"$(dirname "$0")/backup.sh" || echo "!! бэкап не удался (пустая база?) — продолжаю"
$COMPOSE stop egormath-web

echo "==> Пересоздание базы"
$COMPOSE exec -T egormath-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "
  DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`;
  CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  GRANT ALL ON \`$MYSQL_DATABASE\`.* TO \"$MYSQL_USER\"@\"%\";"'

echo "==> Заливка $DUMP"
START=$(date +%s)
case "$DUMP" in
  *.gz) gunzip -c "$DUMP" ;;
  *) cat "$DUMP" ;;
esac | $COMPOSE exec -T egormath-db sh -c 'mysql --default-character-set=utf8mb4 -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
echo "==> Готово за $(( $(date +%s) - START )) с"

echo "==> Число строк в ключевых таблицах (сверить с Timeweb)"
$COMPOSE exec -T egormath-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "
  SELECT table_name, table_rows FROM information_schema.tables
  WHERE table_schema = DATABASE() ORDER BY table_rows DESC LIMIT 15;
  SELECT CONVERT_TZ(NOW(), \"UTC\", \"Europe/Moscow\") AS tz_check;"'

$COMPOSE up -d egormath-web
