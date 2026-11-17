#!/usr/bin/env bash
# Копия egormath в Selectel со стороны Mac (deploy/VPS.md, «Копия в Selectel»). Из корня репозитория.
# Перенесено из chemolymp (scripts/backup-mac.sh).
#   tools/backup-mac.sh setup [--rekey]  окна для ключей S3 → сервер и ~/egormath; cron, проверка
#                                        прав ключа, первая копия, затем watch-install. Повтор без
#                                        --rekey ключи не спрашивает, а только переставляет cron и проверяет
#   tools/backup-mac.sh watch-install    окно для Ping URL healthchecks, задание launchd на этом Mac
#   tools/backup-mac.sh watch            (launchd, раз в день) отчёты сервера в бакете → пинг healthchecks
#   tools/backup-mac.sh check            свежесть копий в бакете (ключом «чтение») и хвост лога сервера
#   tools/backup-mac.sh drill            учения: последний дамп из S3 → временная база в локальном MySQL
#   tools/backup-mac.sh fetch <каталог>  скачать и расшифровать последний набор: база, секреты, media, var
#   … --before 2026-11-20_1200           (у check, drill, fetch) только копии не позже этого момента (МСК):
#                                        после взлома сервера — время взлома, чтобы не взять подложенное
# Ключи S3 Claude не видит: их вставляет владелец в окна macOS, значения сразу уходят в файлы 600.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${BACKUP_SSH:-chemolymp-demo}"
LOCAL_DIR="$HOME/egormath"
export BACKUP_SECRETS_DIR="${BACKUP_SECRETS_DIR:-$LOCAL_DIR/.secrets-backup-reader}"
# Системный Python: у Python с python.org нет корневых сертификатов (CERTIFICATE_VERIFY_FAILED)
# BACKUP_S3_PY — подмена клиента S3 (заглушка для прогона без бакета)
S3=(/usr/bin/python3 "${BACKUP_S3_PY:-$REPO/deploy/vps/backup_s3.py}")
PUBKEY="$REPO/deploy/vps/backup-pubkey.asc"
REMOTE_DIR=/opt/egormath
REMOTE_KEYS="$REMOTE_DIR/data/offsite-keys"
LABEL=ru.egormath.backup-watch
MYSQL_SOCKET="${STAGE_SOCKET:-/tmp/mysql.sock}"

die() { echo "✗ $1" >&2; exit 1; }

key_fpr() {
  gpg --with-colons --import-options show-only --import "$PUBKEY" 2>/dev/null \
    | awk -F: '/^fpr:/ {print $10; exit}'
}

# Без приватного ключа на этом Mac копии не расшифровать (он же — в менеджере паролей)
need_private_key() {
  gpg --list-secret-keys "$(key_fpr)" >/dev/null 2>&1 \
    || die "Нет приватного ключа $(key_fpr) — импортируйте backup-PRIVATE.asc из менеджера паролей: gpg --import"
}

# Только завершённые копии не позже CUTOFF (МСК). Завершённая — с маркером <ключ>.done: сервер
# кладёт его после всех частей, а части оборванной загрузки остаются в бакете без маркера.
# --before сравнивается с LastModified маркера: это время ставит S3, а имя ключа задаёт сервер,
# и взломанный сервер подписал бы подложенную «копию» любой датой. Время в имени тоже не позже
# CUTOFF — иначе подложенная «копия из будущего» стала бы последней.
CUTOFF="$(TZ=Europe/Moscow date +%Y-%m-%d_%H%M)"
list_objects() {
  local cutoff_utc
  cutoff_utc="$(date -u -r "$(TZ=Europe/Moscow date -j -f %Y-%m-%d_%H%M "$CUTOFF" +%s)" +%Y-%m-%dT%H:%M:59)"
  "${S3[@]}" list -l "$1" | awk -F '\t' -v c="$CUTOFF" -v u="$cutoff_utc" '
    $2 ~ /\.done$/ && substr($1, 1, 19) <= u {
      k = substr($2, 1, length($2) - 5)
      if (match(k, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9]/) \
          && substr(k, RSTART, RLENGTH) <= c) print k
    }'
}

# Ключи по времени в имени файла (имя — «<вид>-[full-|incr-]ГГГГ-ММ-ДД_ЧЧММ…»)
by_time() {
  awk -F/ '{s = $NF; if (match(s, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9]/)) print substr(s, RSTART, RLENGTH) "\t" $0}' \
    | LC_ALL=C sort
}

latest_db() { list_objects db/ | by_time | tail -n 1 | cut -f 2; }

# Скачать объект (все его части .part-NNN) и расшифровать в stdout
get_decrypted() {
  local key="$1" tmp parts want
  mkdir -p "$LOCAL_DIR" && chmod 700 "$LOCAL_DIR"
  tmp="$(mktemp -d "$LOCAL_DIR/.get.XXXXXX")"
  "${S3[@]}" get "$key.done" "$tmp/done"
  want="$(sed -n 's/^parts=\([0-9]*\).*/\1/p' "$tmp/done")"
  parts="$("${S3[@]}" list "$key" | grep -E "^${key}(\.part-[0-9]+)?$" || true)"
  [ "$(grep -c . <<< "$parts" || true)" = "$want" ] \
    || { rm -rf "$tmp"; die "$key: в бакете частей $(grep -c . <<< "$parts" || true), в маркере $want"; }
  rm "$tmp/done"
  local i=0 p
  while IFS= read -r p; do
    "${S3[@]}" get "$p" "$tmp/$(printf %03d $i)"
    i=$((i + 1))
  done <<< "$parts"
  cat "$tmp"/* | gpg --batch --quiet --decrypt
  rm -rf "$tmp"
}

ask() {  # $1 — вопрос, $2 — ответ по умолчанию, $3 — "hidden" для скрытого ввода
  local hidden=""; [ "${3:-}" = hidden ] && hidden="with hidden answer"
  osascript -e "text returned of (display dialog \"$1\" default answer \"$2\" $hidden with title \"Бэкап egormath\" buttons {\"Отмена\", \"Готово\"} default button \"Готово\" cancel button \"Отмена\")"
}

setup() {
  local rekey=0
  [ "${1:-}" = --rekey ] && rekey=1
  mkdir -p "$LOCAL_DIR" && chmod 700 "$LOCAL_DIR"
  need_private_key
  echo "==> ssh"
  ssh -o BatchMode=yes "$SERVER" "test -x $REMOTE_DIR/deploy/vps/backup-offsite.sh" \
    || die "На сервере нет deploy/vps/backup-offsite.sh — сначала деплой main со скриптами бэкапа"

  if [ "$rekey" = 1 ] || [ ! -s "$BACKUP_SECRETS_DIR/S3_BACKUP_SECRET" ] \
    || ! ssh "$SERVER" "test -s $REMOTE_KEYS/S3_BACKUP_SECRET"; then
    echo "==> Ключи S3 — в окнах macOS"
    local d pool bucket
    d="$(mktemp -d "$LOCAL_DIR/.kin.XXXXXX")"; chmod 700 "$d"
    trap 'rm -rf "$d"' EXIT
    pool="$(ask 'Selectel: пул бакета (на странице бакета; egormath — ru-6, Москва):' ru-6)"
    bucket="$(ask 'Selectel: имя бакета:' egormath)"
    ask 'Selectel, egormath-backup-writer — вставьте Access key:' '' > "$d/wk"
    ask 'Selectel, egormath-backup-writer — вставьте Secret key:' '' hidden > "$d/ws"
    ask 'Selectel, egormath-backup-reader — вставьте Access key:' '' > "$d/rk"
    ask 'Selectel, egormath-backup-reader — вставьте Secret key:' '' hidden > "$d/rs"
    local f
    for f in wk ws rk rs; do
      [ "$(tr -d '[:space:]' < "$d/$f" | wc -c)" -gt 8 ] || die "Поле $f пустое — прервано"
    done
    printf '%s\n%s\n%s\n' "https://s3.$pool.storage.selcloud.ru" "$pool" "$bucket" > "$d/conf"
    cat "$d/conf" "$d/wk" "$d/ws" | ssh "$SERVER" "umask 077; mkdir -p $REMOTE_KEYS && chmod 700 $REMOTE_KEYS && cd $REMOTE_KEYS && \
      read -r e && read -r r && read -r b && read -r k && read -r s; \
      printf %s \"\$e\" > S3_BACKUP_ENDPOINT && printf %s \"\$r\" > S3_BACKUP_REGION && printf %s \"\$b\" > S3_BACKUP_BUCKET && \
      printf %s \"\$k\" > S3_BACKUP_KEY_ID && printf %s \"\$s\" > S3_BACKUP_SECRET && \
      echo 'сервер: ключ writer записан'"
    mkdir -p "$BACKUP_SECRETS_DIR" && chmod 700 "$BACKUP_SECRETS_DIR"
    ( umask 077; cd "$BACKUP_SECRETS_DIR"
      sed -n 1p "$d/conf" | tr -d '\n' > S3_BACKUP_ENDPOINT
      sed -n 2p "$d/conf" | tr -d '\n' > S3_BACKUP_REGION
      sed -n 3p "$d/conf" | tr -d '\n' > S3_BACKUP_BUCKET
      tr -d '\n' < "$d/rk" > S3_BACKUP_KEY_ID; tr -d '\n' < "$d/rs" > S3_BACKUP_SECRET )
    echo "Mac: ключ reader записан в $BACKUP_SECRETS_DIR"
    rm -rf "$d"; trap - EXIT
  fi

  echo "==> Сервер: cron (строка backup-offsite.sh из crontab.example)"
  ssh "$SERVER" "line=\$(grep 'backup-offsite.sh daily' $REMOTE_DIR/deploy/vps/crontab.example) && \
    { crontab -l 2>/dev/null | grep -v 'backup-offsite.sh'; echo \"\$line\"; } | crontab - && crontab -l | grep backup-offsite"

  echo "==> Сервер: подпись, права ключа, первая копия (media и var целиком — несколько минут)"
  ssh "$SERVER" "cd $REMOTE_DIR && python3 deploy/vps/backup_s3.py selftest \
    && BACKUP_SECRETS_DIR=$REMOTE_KEYS python3 deploy/vps/backup_s3.py check-write-only \
    && deploy/vps/backup-offsite.sh daily; rc=\$?; tail -n 8 data/offsite/offsite.log; exit \$rc"

  echo "==> Mac: копии видны ключом reader"
  check
  watch_install
}

# Сторож. healthchecks.io не принимает запросы с российских IP, поэтому сервер оставляет отчёт
# в бакете (_status/daily/<время>-<режим>-ok|fail), а этот Mac раз в день читает отчёты и пингует
# healthchecks: был fail после прошлого запуска watch или за 26 ч нет ни одного ok — /fail
# с причиной, иначе успех. Сбои считаются только с прошлого прочтения (момент — в
# ~/egormath/.backup-watch-last, обновляется, когда healthchecks принял пинг).
watch() {
  local url since seen latest recent fails oks msg suffix
  since="$(date -u -v-26H +%Y-%m-%dT%H:%M:%S)"
  url="$(cat "$BACKUP_SECRETS_DIR/BACKUP_PING_URL" 2>/dev/null || true)"
  [ -n "$url" ] || { echo "адреса healthchecks нет — пропускаю"; return 0; }
  seen="$(cat "$LOCAL_DIR/.backup-watch-last" 2>/dev/null || echo "$since")"
  if ! recent="$("${S3[@]}" list -l "_status/daily/" \
    | awk -F '\t' -v s="$since" -v z="$seen" 'BEGIN {if (z < s) s = z}
        substr($1, 1, 19) >= s {n = split($2, a, "/"); print substr($1, 1, 19) "\t" a[n]}')"; then
    echo "✗ не удалось прочитать отчёты из бакета"
    curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "не удалось прочитать отчёты из бакета" \
      "$url/fail" || echo "!! healthchecks не ответил"
    return 0
  fi
  latest="$(cut -f 1 <<< "$recent" | LC_ALL=C sort | tail -n 1)"
  fails="$(awk -F '\t' -v s="$seen" '$1 > s && $2 ~ /-fail$/ {print $2}' <<< "$recent")"
  oks="$(awk -F '\t' -v s="$since" '$1 >= s && $2 ~ /-ok$/ {print $2}' <<< "$recent")"
  if [ -n "$fails" ]; then
    echo "✗ сбои с прошлой проверки: $(tr '\n' ' ' <<< "$fails")— лог сервера data/offsite/offsite.log"
    msg="сбои: $fails"; suffix=/fail
  elif [ -z "$oks" ]; then
    echo "✗ за 26 ч нет отчёта об успешной копии"
    msg="за 26 ч нет отчёта ok"; suffix=/fail
  else
    echo "✓ $(tail -n 1 <<< "$oks")"
    msg="$(tail -n 1 <<< "$oks")"; suffix=""
  fi
  if curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "$msg" "$url$suffix"; then
    [ -z "$latest" ] || echo "$latest" > "$LOCAL_DIR/.backup-watch-last"
  else
    echo "!! healthchecks не ответил — эти отчёты учтутся в следующий раз"
  fi
}

# Адрес healthchecks — в окне; скрипты — копией в ~/egormath/tools (launchd не читает папку
# Dropbox без отдельного разрешения); задание launchd — раз в день в 10:23, пропущенное из-за
# сна Mac выполняется при пробуждении.
watch_install() {
  local plist="$HOME/Library/LaunchAgents/$LABEL.plist" file old answer
  mkdir -p "$BACKUP_SECRETS_DIR" "$LOCAL_DIR/tools" "$LOCAL_DIR/deploy/vps" "$HOME/Library/LaunchAgents"
  file="$BACKUP_SECRETS_DIR/BACKUP_PING_URL"
  old="$(cat "$file" 2>/dev/null || true)"
  answer="$(ask 'healthchecks.io, «egormath: копия в Selectel» — Ping URL (нет проверки — оставьте пустым):' "$old")"
  ( umask 077; tr -d '[:space:]' <<< "$answer" > "$file.new" && mv "$file.new" "$file" )
  if [ ! "$REPO/tools/backup-mac.sh" -ef "$LOCAL_DIR/tools/backup-mac.sh" ]; then
    install -m 755 "$REPO/tools/backup-mac.sh" "$LOCAL_DIR/tools/"
    install -m 755 "$REPO/deploy/vps/backup_s3.py" "$LOCAL_DIR/deploy/vps/"
    install -m 644 "$PUBKEY" "$LOCAL_DIR/deploy/vps/"
  fi
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$LOCAL_DIR/tools/backup-mac.sh</string><string>watch</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>23</integer></dict>
  <key>StandardOutPath</key><string>$LOCAL_DIR/backup-watch.log</string>
  <key>StandardErrorPath</key><string>$LOCAL_DIR/backup-watch.log</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "==> Сторож: launchd $LABEL (каждый день в 10:23), лог $LOCAL_DIR/backup-watch.log"
  watch
}

check() {
  local today yesterday last prefix
  today="$(TZ=Europe/Moscow date +%Y-%m-%d)"
  yesterday="$(TZ=Europe/Moscow date -v-1d +%Y-%m-%d)"
  for prefix in db/ secrets/ media/ var/; do
    last="$(list_objects "$prefix" | by_time | tail -n 1 | cut -f 2)"
    echo "${prefix%/}: ${last:-нет копий}"
  done
  last="$(list_objects db/ | grep -v -- '-premigrate-' | by_time | tail -n 1 | cut -f 2)"
  case "$last" in
    db/"$today"/*|db/"$yesterday"/*) echo "✓ ночная копия базы свежая" ;;
    *) echo "✗ ночной копии базы за сегодня и вчера нет" ;;
  esac
  echo "==> Лог на сервере"
  ssh -o BatchMode=yes "$SERVER" "tail -n 10 $REMOTE_DIR/data/offsite/offsite.log" || echo "(ssh не прошёл)"
}

# Учения: дамп заливается во временную базу локального MySQL (Homebrew, как у tools/stage.sh),
# считаются строки ключевых таблиц, база удаляется.
drill() {
  need_private_key
  local key t0 db=egormath_drill dump
  local mysql=(mysql -uroot "--socket=$MYSQL_SOCKET")
  command -v mysql >/dev/null || die "нет клиента mysql (brew install mysql)"
  t0="$(date +%s)"
  key="$(latest_db)"; [ -n "$key" ] || die "В бакете нет дампов"
  echo "==> Копия: $key"
  dump="$(mktemp "$LOCAL_DIR/.drill.XXXXXX")"
  get_decrypted "$key" > "$dump"
  "${mysql[@]}" -e "DROP DATABASE IF EXISTS $db; CREATE DATABASE $db CHARACTER SET utf8mb4"
  gzip -dc "$dump" | "${mysql[@]}" "$db"
  "${mysql[@]}" -t "$db" -e "
    SELECT 'users' AS t, count(*) AS n FROM auth_user
    UNION ALL SELECT 'tasks', count(*) FROM problems_task
    UNION ALL SELECT 'worksheets', count(*) FROM worksheets_worksheet
    UNION ALL SELECT 'migrations', count(*) FROM django_migrations;"
  "${mysql[@]}" -e "DROP DATABASE $db"; rm -f "$dump"
  echo "==> media: полных архивов $(list_objects media/ | grep -c 'media-full' || true), var: $(list_objects var/ | grep -c 'var-full' || true)"
  echo "==> Учения прошли за $(( $(date +%s) - t0 )) с (локальная база удалена)"
}

# Последний полный архив каталога и все более поздние — по порядку
restore_dir() {  # $1 — media|var, $2 — куда
  local name="$1" out="$2" archives full key
  archives="$(list_objects "$name/" | by_time)"
  full="$(printf '%s\n' "$archives" | grep -- "/$name-full-" | tail -n 1 | cut -f 1)"
  [ -n "$full" ] || die "В бакете нет полного архива $name"
  mkdir -p "$out"
  printf '%s\n' "$archives" | awk -F'\t' -v f="$full" '$1 >= f {print $2}' | while IFS= read -r key; do
    echo "==> $name: $key"
    get_decrypted "$key" | tar -xzf - -C "$out"
  done
}

fetch() {
  local out="${1:?usage: tools/backup-mac.sh fetch <каталог>}" key
  need_private_key
  mkdir -p "$out/secrets"; chmod 700 "$out"
  key="$(latest_db)"; [ -n "$key" ] || die "В бакете нет дампов"
  echo "==> База: $key"
  get_decrypted "$key" > "$out/$(basename "$key" .gpg | sed -E 's/-[0-9a-f]{16}\././')"
  key="$(list_objects secrets/ | by_time | tail -n 1 | cut -f 2)"; [ -n "$key" ] || die "В бакете нет архива секретов"
  echo "==> Секреты: $key"
  get_decrypted "$key" | tar -xzf - -C "$out/secrets"
  restore_dir media "$out/media"
  restore_dir var "$out/var"
  echo "==> Готово: $out — дамп для import-db.sh, media/ и var/ — в data/, secrets/ — data/secrets и .env (deploy/VPS.md)"
  ls -la "$out"
}

CMD="${1:-}"; [ $# -gt 0 ] && shift
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --before)
      [[ "${2:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}$ ]] || die "--before ГГГГ-ММ-ДД_ЧЧММ (МСК)"
      CUTOFF="$2"; echo "==> Только копии не позже $CUTOFF"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
case "$CMD" in
  setup) setup "$@" ;;
  check) check ;;
  watch) watch ;;
  watch-install) watch_install ;;
  drill) drill ;;
  fetch) fetch "$@" ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
