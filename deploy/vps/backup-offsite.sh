#!/usr/bin/env bash
# Копия вне Timeweb: дамп MySQL, media, var и секреты → бакет Selectel, всё зашифровано gpg.
# Схема, настройка и восстановление — deploy/VPS.md, «Копия в Selectel». Перенесено из chemolymp
# (scripts/backup-offsite.sh): ключ сервера только на запись, отчёты сторожу — в бакет.
#   deploy/vps/backup-offsite.sh daily       дамп базы; секреты — если менялись или раз в неделю;
#                                            media и var — полный архив раз в неделю, иначе только
#                                            новые и изменённые файлы (cron, crontab.example)
#   deploy/vps/backup-offsite.sh premigrate  только дамп базы (зовёт deploy.sh перед migrate);
#                                            без настройки — тихо пропускает
#
# Настройки — файлы в data/offsite-keys/ (права 600; не в .env и не в data/secrets — их видят
# контейнеры): S3_BACKUP_ENDPOINT, S3_BACKUP_REGION, S3_BACKUP_BUCKET, S3_BACKUP_KEY_ID,
# S3_BACKUP_SECRET. Кладёт их tools/backup-mac.sh setup из окон macOS.
# Ключ S3 сервера может только загружать, а в имени каждой копии — случайный суффикс, которого нет
# ни в логе, ни на диске: взломанный сервер копии не прочитает, не сотрёт и не перезапишет.
# Шифрование — публичным ключом deploy/vps/backup-pubkey.asc; приватный — только у владельца.
# Лог и состояние — data/offsite/. Время в именах и логе — московское.
set -Eeuo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
source "$HERE/lib.sh"

MODE="${1:-}"
SECRETS_DIR="${BACKUP_SECRETS_DIR:-$DATA_DIR/offsite-keys}"
STATE_DIR="${BACKUP_STATE_DIR:-$DATA_DIR/offsite}"
LOG_FILE="$STATE_DIR/offsite.log"
PUBKEY="$HERE/backup-pubkey.asc"
# BACKUP_S3_PY — подмена клиента S3 для прогона без бакета (заглушка, пишущая в каталог)
S3_PY="${BACKUP_S3_PY:-$HERE/backup_s3.py}"
LOCK_WAIT="${BACKUP_LOCK_WAIT:-1800}"
# Полный архив media/var и секреты — не реже раза в неделю: бакет сам удаляет файлы через 90 дней,
# и без повторной загрузки неизменные данные пропали бы из копии
REFRESH_SECONDS=$((7 * 86400 - 3600))
# Один PUT в S3 — до 5 ГиБ, но долгий запрос обрывается: 17.11.2026 архив media в 478 МБ одним
# PUT трижды упал с «EOF occurred in violation of protocol». Поэтому архивы идут потоком и режутся
# на части по 256 МиБ (.part-000, …): сбой повторяет одну часть, на диске — не больше одной части
PART_BYTES=$((256 * 1024 * 1024))
# Свободное место, ниже которого архив не начинается: часть архива + запас для MySQL
MIN_FREE_KB=$((PART_BYTES / 1024 + 3 * 1024 * 1024))
export TZ=Europe/Moscow BACKUP_SECRETS_DIR="$SECRETS_DIR"

umask 077
mkdir -p "$STATE_DIR"
WORK_DIR=""

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$MODE] $1" >> "$LOG_FILE"
}

# Сторож. Успех сообщает только daily (иначе копия перед деплоем «закрашивала» бы пропавшую
# ночную); premigrate — только об ошибке. healthchecks.io не принимает запросы с российских IP,
# поэтому сервер кладёт в бакет пустой объект _status/daily/<время>-<режим>-ok|fail, а Mac
# (tools/backup-mac.sh watch, launchd) читает отчёты ключом reader и пингует healthchecks.
ping_watchdog() {
  local status=ok
  [ -n "$1" ] || [ "$MODE" = daily ] || return 0
  [ -n "$1" ] && status=fail
  : > "$STATE_DIR/status.empty"
  put "$STATE_DIR/status.empty" "_status/daily/$(date +%Y-%m-%d_%H%M%S)-$MODE-$status" \
    || log "⚠️  Отчёт сторожу в бакет не загрузился"
}

cleanup() {
  if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
    gpgconf --homedir "$WORK_DIR/gnupg" --kill all >/dev/null 2>&1 || true
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

on_error() {
  local code=$?
  log "❌ Ошибка (код $code, строка $1)"
  # Ошибка в звене конвейера («tar | upload_stream») — подкоманда: выходим из неё, а отчёт
  # сторожу и сообщение даст основной процесс, когда упадёт весь конвейер (иначе — два fail)
  [ "$BASHPID" = "$$" ] || exit "$code"
  echo "backup-offsite.sh $MODE: ошибка, см. $LOG_FILE" >&2
  ping_watchdog /fail
  exit "$code"
}
trap 'on_error $LINENO' ERR

sha256() { sha256sum | cut -d ' ' -f 1; }

# «Пора ли грузить»: $1 — имя в data/offsite, $2 — отпечаток данных. Да — если отпечаток
# сменился или прошлая загрузка старше недели.
due() {
  local at
  [ "$2" = "$(cat "$STATE_DIR/last_$1" 2>/dev/null || true)" ] || return 0
  at="$(cat "$STATE_DIR/last_$1_at" 2>/dev/null || echo 0)"
  [ $(($(date +%s) - at)) -ge "$REFRESH_SECONDS" ]
}
remember() {
  echo "$2" > "$STATE_DIR/last_$1"
  date +%s > "$STATE_DIR/last_$1_at"
}

# Шифруем публичным ключом во временном keyring: ~/.gnupg не трогаем. -z 0: на входе уже gzip.
encrypt() {
  local gnupghome="$WORK_DIR/gnupg" fpr
  if [ ! -d "$gnupghome" ]; then
    mkdir -m 700 "$gnupghome"
    gpg --homedir "$gnupghome" --batch --quiet --import "$PUBKEY"
  fi
  fpr="$(gpg --homedir "$gnupghome" --batch --with-colons --fingerprint | awk -F: '/^fpr:/ {print $10; exit}')"
  [ -n "$fpr" ] || { log "❌ В $PUBKEY нет ключа"; return 1; }
  gpg --homedir "$gnupghome" --batch --yes --trust-model always -z 0 --recipient "$fpr" --encrypt
}

put() { python3 "$S3_PY" put "$1" "$2"; }

# Случайный суффикс имени: PutObject перезаписывает объект с тем же ключом, а версионирования
# в бакете нет. Без списка объектов (ключ сервера его не получает) чужое имя не угадать.
nonce() { od -An -N8 -tx1 /dev/urandom | tr -d ' \n'; }

free_kb() { df -Pk "$STATE_DIR" | awk 'NR == 2 {print $4}'; }

# Поток со stdin → gpg → части по 256 МиБ, каждая сразу в S3 и с диска; последним — маркер
# <ключ>.done (число частей и байт). tools/backup-mac.sh берёт только копии с маркером:
# части оборванной загрузки ключ сервера удалить не может, и без маркера неполный архив
# выдавался бы за последнюю копию. $1 — ключ копии.
upload_stream() {
  local key="$1" parts total
  if [ "$(free_kb)" -lt "$MIN_FREE_KB" ]; then
    log "❌ На диске свободно $(($(free_kb) / 1024)) МБ, нужно не меньше $((MIN_FREE_KB / 1024)) — $key не снят"
    return 1
  fi
  export BACKUP_S3_PY="$S3_PY" BACKUP_PART_SIZES="$WORK_DIR/part-sizes" BACKUP_KEY="$key"
  : > "$BACKUP_PART_SIZES"
  # shellcheck disable=SC2016 — переменные раскрывает shell внутри split, а не этот
  encrypt | split -b "$PART_BYTES" -d -a 3 --filter='cat > "$FILE" && wc -c < "$FILE" >> "$BACKUP_PART_SIZES" \
      && python3 "$BACKUP_S3_PY" put "$FILE" "$BACKUP_KEY.${FILE##*.}" && rm "$FILE"' - "$WORK_DIR/up.part-"
  parts="$(wc -l < "$BACKUP_PART_SIZES" | tr -d ' ')"
  total="$(awk '{s += $1} END {print s + 0}' "$BACKUP_PART_SIZES")"
  [ "$parts" -gt 0 ] || { log "❌ $key: пустой поток"; return 1; }
  printf 'parts=%s bytes=%s\n' "$parts" "$total" > "$WORK_DIR/done"
  put "$WORK_DIR/done" "$key.done"
  # В лог — без суффикса: лог лежит на сервере
  log "✅ $(sed -E 's/-[0-9a-f]{16}\./-…./' <<< "$key") ($total байт, частей: $parts)"
}

# Дамп MySQL — тем же mysqldump, что backup.sh; перед загрузкой проверяем, что gzip цел и
# mysqldump дошёл до конца (последняя строка «-- Dump completed»).
backup_db() {
  local dump="$WORK_DIR/db.sql.gz" suffix="$1"
  $COMPOSE exec -T egormath-db sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --single-transaction --routines --no-tablespaces --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' \
    | gzip > "$dump"
  gzip -t "$dump" || { log "❌ Дамп базы — битый gzip"; return 1; }
  zcat "$dump" | tail -n 1 | grep -q '^-- Dump completed' \
    || { log "❌ Дамп базы оборван (нет «-- Dump completed»)"; return 1; }
  upload_stream "db/$(date +%Y-%m-%d)/egormath-$(date +%Y-%m-%d_%H%M)$suffix-$(nonce).sql.gz.gpg" < "$dump"
}

# Секреты: без DJANGO_SECRET_KEY, ключей API и .env стек с нуля не поднять. data/secrets, .env,
# crontab и rclone.conf — тем же набором, что архив секретов backup.sh, но публичным ключом gpg,
# без пароля BACKUP_SECRETS_PASSPHRASE.
backup_secrets() {
  local bundle="$WORK_DIR/secrets" fp
  mkdir -p "$bundle"
  cp -a "$DATA_DIR/secrets" "$bundle/secrets"
  cp "$ENV_FILE" "$bundle/env"
  crontab -l > "$bundle/crontab" 2>/dev/null || true
  [ -r "$HOME/.config/rclone/rclone.conf" ] && cp "$HOME/.config/rclone/rclone.conf" "$bundle/rclone.conf"
  fp="$(cd "$bundle" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 cat | sha256)"
  if ! due secrets "$fp"; then
    log "= Секреты не менялись, пропускаю"
    return 0
  fi
  tar -czf - -C "$bundle" . \
    | upload_stream "secrets/$(date +%Y-%m)/secrets-$(date +%Y-%m-%d_%H%M)-$(nonce).tar.gz.gpg"
  remember secrets "$fp"
}

# Каталог data/<name> (media, var): полный архив раз в неделю, в остальные ночи — только новые
# и изменённые файлы (опись «путь<TAB>размер<TAB>mtime» против описи всего, что уже уехало
# с последнего полного). Удалённые файлы инкремент не отражает: при восстановлении они
# вернутся — лишний файл безопаснее потерянного. Восстановление — полный и все более поздние.
backup_dir() {
  local name="$1" src="$DATA_DIR/$1" kind list="$WORK_DIR/$1.list" manifest="$WORK_DIR/$1.manifest"
  local stored="$STATE_DIR/${name}_manifest" full_at
  [ -d "$src" ] || { log "= $src нет, пропускаю"; return 0; }
  (cd "$src" && find . -type f -not -path '*/__pycache__/*' -printf '%P\t%s\t%T@\n') \
    | LC_ALL=C sort > "$manifest"
  full_at="$(cat "$STATE_DIR/last_${name}_full_at" 2>/dev/null || echo 0)"
  if [ ! -f "$stored" ] || [ $(($(date +%s) - full_at)) -ge "$REFRESH_SECONDS" ]; then
    kind=full
    cut -f 1 "$manifest" > "$list"
  else
    kind=incr
    LC_ALL=C comm -23 "$manifest" "$stored" | cut -f 1 > "$list"
    if [ ! -s "$list" ]; then
      log "= $name: новых и изменённых файлов нет ($(wc -l < "$manifest" | tr -d ' ') всего)"
      return 0
    fi
  fi
  tar -C "$src" -czf - --verbatim-files-from -T "$list" \
    | upload_stream "$name/$(date +%Y-%m-%d)/$name-$kind-$(date +%Y-%m-%d_%H%M)-$(nonce).tar.gz.gpg"
  if [ "$kind" = full ]; then
    cp "$manifest" "$stored"
    date +%s > "$STATE_DIR/last_${name}_full_at"
  else
    LC_ALL=C sort -u "$stored" "$manifest" -o "$stored"
  fi
  log "  $name ($kind): файлов в архиве $(wc -l < "$list" | tr -d ' ')"
}

case "$MODE" in
  daily|premigrate) ;;
  *)
    sed -n '2,10p' "$0" >&2
    exit 2 ;;
esac

# Без настройки (до tools/backup-mac.sh setup) — запись в лог и выход без ошибки:
# о молчании предупредит сторож на Mac.
if [ ! -s "$SECRETS_DIR/S3_BACKUP_BUCKET" ]; then
  [ "$MODE" = premigrate ] || log "— Копия в Selectel не настроена ($SECRETS_DIR), см. deploy/VPS.md"
  exit 0
fi

# Из cron вывод никто не читает — ошибки mysqldump, tar, gpg и S3 пишем в лог
exec 2>>"$LOG_FILE"

# Не запускаемся дважды одновременно. Ждём, а не пропускаем, иначе premigrate
# отчитается об успехе без копии.
exec 9>"$STATE_DIR/lock"
if ! flock -w "$LOCK_WAIT" 9; then
  log "❌ Предыдущий запуск идёт больше $LOCK_WAIT с — похоже, завис"
  ping_watchdog /fail
  exit 1
fi

WORK_DIR="$(mktemp -d "$STATE_DIR/tmp.XXXXXX")"

case "$MODE" in
  daily)
    backup_db ""
    backup_secrets
    backup_dir media
    backup_dir var ;;
  premigrate)
    backup_db "-premigrate" ;;
esac

ping_watchdog ""
