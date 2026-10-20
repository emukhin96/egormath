#!/usr/bin/env bash
# Почта сайта: секреты EMAIL_* в data/secrets по ответам в терминале, проверка
# входа по SMTP до записи, перезапуск egormath-web и тестовое письмо.
#   ssh -t chemolymp-demo /opt/egormath/deploy/vps/mail-setup.sh           настроить
#   ssh -t chemolymp-demo /opt/egormath/deploy/vps/mail-setup.sh --check   только показать, что задано, и отправить тест
# До слияния ветки файл копируют в /tmp на сервере (deploy/MAIL.md, раздел 5).
# Безопасность: пароль ящика вводится без эха и не попадает в аргументы,
# историю shell, логи и вывод; в проверку SMTP он передаётся переменной
# окружения дочернего python3 и после записи файлов стирается. Файлы секретов
# создаются с правами 600 от пользователя deploy; значений скрипт не печатает.
set -euo pipefail
LIB="$(dirname "$0")/lib.sh"
[ -r "$LIB" ] || LIB=/opt/egormath/deploy/vps/lib.sh
# shellcheck source=lib.sh
source "$LIB"
SECRETS="$DATA_DIR/secrets"
[ -d "$SECRETS" ] || { echo "mail-setup.sh: нет каталога $SECRETS" >&2; exit 1; }

current() { [ -r "$SECRETS/$1" ] && tr -d '\r\n' < "$SECRETS/$1" || true; }
mask_present() { [ -r "$SECRETS/$1" ] && echo "задан" || echo "нет"; }

show() {
  echo "==> Секреты почты в $SECRETS"
  echo "   EMAIL_HOST:             ${EMAIL_HOST_CUR:-(нет — почта выключена)}"
  echo "   EMAIL_PORT:             ${EMAIL_PORT_CUR:-(нет — 587 по умолчанию)}"
  echo "   EMAIL_HOST_USER:        ${EMAIL_USER_CUR:-(нет)}"
  echo "   EMAIL_HOST_PASSWORD:    $(mask_present EMAIL_HOST_PASSWORD)"
  echo "   DEFAULT_FROM_EMAIL:     $(current DEFAULT_FROM_EMAIL)"
  echo "   PROPOSAL_NOTIFY_EMAILS: ${EDITORS_CUR:-(нет — письма о предложениях не уходят)}"
}

mail_check() { # mail_check <адрес>
  echo "==> manage.py mail_check $1"
  $COMPOSE exec -T egormath-web python manage.py mail_check "$1"
}

dns_hint() { # dns_hint <домен ящика>: что видно снаружи, без оценки
  command -v dig >/dev/null 2>&1 || return 0
  echo "==> DNS $1 (как видит сервер; полная таблица — deploy/MAIL.md, раздел 4)"
  for t in MX TXT; do
    echo "   $t: $(dig +short +time=2 +tries=1 "$t" "$1" 2>/dev/null | tr '\n' ' ')"
  done
  echo "   DMARC: $(dig +short +time=2 +tries=1 TXT "_dmarc.$1" 2>/dev/null | tr '\n' ' ')"
}

EMAIL_HOST_CUR="$(current EMAIL_HOST)"
EMAIL_PORT_CUR="$(current EMAIL_PORT)"
EMAIL_USER_CUR="$(current EMAIL_HOST_USER)"
EDITORS_CUR="$(current PROPOSAL_NOTIFY_EMAILS)"

if [ "${1:-}" = "--check" ]; then
  show
  [ -n "$EMAIL_HOST_CUR" ] || { echo "!! EMAIL_HOST не задан: запустите без --check" >&2; exit 1; }
  TO="${2:-${EDITORS_CUR%%,*}}"
  [ -n "$TO" ] || { echo "!! куда слать тест: mail-setup.sh --check адрес@example.com" >&2; exit 1; }
  dns_hint "${EMAIL_USER_CUR#*@}"
  mail_check "$TO"
  exit 0
fi

[ -t 0 ] && [ -t 1 ] || { echo "mail-setup.sh: нужен терминал (ssh -t …): пароль вводится интерактивно" >&2; exit 1; }

ask() { # ask VAR "подсказка" "по умолчанию"
  local reply
  read -r -p "$2 [${3:-}]: " reply
  printf -v "$1" '%s' "${reply:-$3}"
}

show
echo
echo "Enter — оставить значение в скобках. Инструкция: deploy/MAIL.md, раздел 5."
ask HOST "SMTP-сервер" "${EMAIL_HOST_CUR:-smtp.timeweb.ru}"
ask PORT "Порт (465 — SSL, 587 — STARTTLS)" "${EMAIL_PORT_CUR:-465}"
ask USER_ADDR "Ящик (логин — полный адрес)" "${EMAIL_USER_CUR:-no-reply@math.emukhin.ru}"
case "$USER_ADDR" in *@*) ;; *) echo "!! логин должен быть адресом ящика: Timeweb принимает письма только от ящика авторизации" >&2; exit 1 ;; esac
case "$PORT" in 465|587|25|2525) ;; *) echo "!! странный порт: $PORT" >&2; exit 1 ;; esac

if [ -r "$SECRETS/EMAIL_HOST_PASSWORD" ] && [ "$USER_ADDR" = "$EMAIL_USER_CUR" ]; then
  read -rs -p "Пароль ящика (ввод скрыт; Enter — оставить текущий): " PASS; echo
  [ -n "$PASS" ] || PASS="$(cat "$SECRETS/EMAIL_HOST_PASSWORD")"
else
  read -rs -p "Пароль ящика $USER_ADDR (ввод скрыт): " PASS; echo
fi
[ -n "$PASS" ] || { echo "!! пустой пароль" >&2; exit 1; }
read -rs -p "Пароль ещё раз: " PASS2; echo
[ "$PASS" = "$PASS2" ] || { echo "!! пароли не совпали" >&2; exit 1; }
unset PASS2
ask EDITORS "Адреса редакторов через запятую (письма о новых предложениях)" "$EDITORS_CUR"
ask TEST_TO "Куда отправить тестовое письмо" "${EDITORS%%,*}"
[ -n "$TEST_TO" ] || { echo "!! нужен адрес для теста" >&2; exit 1; }

echo "==> Проверяю вход на $HOST:$PORT как $USER_ADDR"
if ! EMAIL_HOST="$HOST" EMAIL_PORT="$PORT" EMAIL_USER="$USER_ADDR" EMAIL_PASS="$PASS" python3 - <<'PY'
import os
import smtplib
import ssl
import sys

host, port = os.environ['EMAIL_HOST'], int(os.environ['EMAIL_PORT'])
user, password = os.environ['EMAIL_USER'], os.environ['EMAIL_PASS']
context = ssl.create_default_context()
try:
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        server.starttls(context=context)
    server.login(user, password)
    server.quit()
except smtplib.SMTPAuthenticationError as error:
    print(f'!! сервер не принял логин или пароль: {error.smtp_code} '
          f'{error.smtp_error.decode(errors="replace") if isinstance(error.smtp_error, bytes) else error.smtp_error}')
    sys.exit(2)
except (OSError, smtplib.SMTPException) as error:
    print(f'!! не удалось подключиться к {host}:{port}: {error}')
    sys.exit(3)
print('   вход по SMTP прошёл')
PY
then
  read -r -p "Записать секреты несмотря на ошибку? [y/N] " yn
  case "$yn" in y|Y|д|Д) ;; *) echo "ничего не записано"; exit 1 ;; esac
fi

# Файлы: без завершающего перевода строки (read_secret и так strip'ает),
# временный файл + mv, права 600 — как у остальных секретов.
umask 077
put() { printf '%s' "$2" > "$SECRETS/$1.tmp" && mv -f "$SECRETS/$1.tmp" "$SECRETS/$1" && chmod 600 "$SECRETS/$1"; }
put EMAIL_HOST "$HOST"
put EMAIL_PORT "$PORT"
put EMAIL_HOST_USER "$USER_ADDR"
put EMAIL_HOST_PASSWORD "$PASS"
unset PASS
if [ -n "$EDITORS" ]; then put PROPOSAL_NOTIFY_EMAILS "$EDITORS"; else rm -f "$SECRETS/PROPOSAL_NOTIFY_EMAILS"; fi
# Отправитель выводится из ящика в core/settings.py; явный файл с другим
# адресом Timeweb отвергнет — убираем, если он не про этот ящик.
if [ -r "$SECRETS/DEFAULT_FROM_EMAIL" ] && ! grep -q "$USER_ADDR" "$SECRETS/DEFAULT_FROM_EMAIL"; then
  echo "!! DEFAULT_FROM_EMAIL задан и не содержит $USER_ADDR — удаляю, отправитель будет «Математика <$USER_ADDR>»"
  rm -f "$SECRETS/DEFAULT_FROM_EMAIL"
fi
echo "==> Записано: EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD${EDITORS:+, PROPOSAL_NOTIFY_EMAILS}"

echo "==> Перезапуск egormath-web (секреты читаются при старте)"
$COMPOSE restart egormath-web
for _ in $(seq 1 20); do
  $COMPOSE exec -T egormath-web python /app/deploy/vps/healthcheck.py >/dev/null 2>&1 && break
  sleep 3
done

dns_hint "${USER_ADDR#*@}"
mail_check "$TEST_TO"
echo "==> Готово. Проверьте письмо в ящике $TEST_TO (и папку «Спам»): в заголовках должны быть SPF и DKIM PASS — deploy/MAIL.md, раздел 6."
