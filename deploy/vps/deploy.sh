#!/usr/bin/env bash
###############################################################################
# Деплой egormath на VPS (общий сервер с chemolymp):
#   ssh chemolymp-demo '/opt/egormath/deploy/vps/deploy.sh [git-ref]'   (по умолчанию main)
#
# fetch → checkout → сборка образа → бэкап → check --deploy → migrate →
# seed_rubricator → collectstatic → пересоздание контейнеров → сайт в общем
# Caddy → healthz. По образцу scripts/deploy.sh chemolymp.
###############################################################################
set -euo pipefail

REF="${1:-main}"
source "$(dirname "$(readlink -f "$0")")/lib.sh"
cd "$APP_DIR"

if [ -z "${DEPLOY_REEXEC:-}" ]; then
  echo "==> Deploying $REF to $APP_DIR"
  git fetch --all --tags --prune
  # -f: отслеживаемые файлы на сервере руками не правятся (настройки — в .env
  # и data/secrets/, они не в git).
  git checkout -q -f --detach "origin/$REF" 2>/dev/null || git checkout -q -f --detach "$REF"
  chmod +x deploy/vps/*.sh
  # bash держит открытым старый deploy.sh — перезапускаемся из нового кода.
  DEPLOY_REEXEC=1 exec "$APP_DIR/deploy/vps/deploy.sh" "$REF"
fi
echo "==> At $(git rev-parse --short HEAD): $(git log -1 --pretty=%s)"

mkdir -p "$DATA_DIR"/{secrets,media,var,cache,live,staticfiles,mysql,backups,logs}
docker network inspect edge >/dev/null 2>&1 || docker network create edge

echo "==> Building image"
# Каталог данных внутри репозитория не должен попадать в образ (секреты!).
grep -qxF data .dockerignore || { echo "!! в .dockerignore нет строки data — сборка остановлена"; exit 1; }
$COMPOSE build egormath-web
# Старые слои образа (в т. ч. собранные до исправления .dockerignore) не копим.
docker image prune -f --filter "label=com.docker.compose.project=egormath" >/dev/null 2>&1 || true

echo "==> Database"
$COMPOSE up -d --wait egormath-db
if $COMPOSE ps --status running --services 2>/dev/null | grep -q '^egormath-web$'; then
  echo "==> Backup before migrate"
  "$APP_DIR/deploy/vps/backup.sh" || echo "!! backup failed, continuing"
fi

RUN="$COMPOSE run --rm --no-deps -T egormath-web python manage.py"
echo "==> check --deploy"
$RUN check --deploy --fail-level ERROR
echo "==> migrate"
$RUN migrate --noinput
echo "==> seed_rubricator"
$RUN seed_rubricator
echo "==> collectstatic"
$RUN collectstatic --noinput

echo "==> Starting services"
$COMPOSE up -d --remove-orphans

echo "==> Site in shared Caddy"
HOSTS="$(env_get EGORMATH_HOSTS)"
if [ -n "$HOSTS" ] && [ -d /opt/caddy/sites ]; then
  sed "s|__HOSTS__|$HOSTS|" deploy/vps/egormath.caddy.template > /opt/caddy/sites/egormath.caddy.new
  if ! cmp -s /opt/caddy/sites/egormath.caddy.new /opt/caddy/sites/egormath.caddy; then
    mv /opt/caddy/sites/egormath.caddy.new /opt/caddy/sites/egormath.caddy
    CADDY=$(docker ps -q --filter label=com.docker.compose.project=chemolymp \
                         --filter label=com.docker.compose.service=caddy | head -n 1)
    if [ -n "$CADDY" ]; then
      # Caddy проверяет конфиг целиком; при ошибке остаётся старый.
      docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
      echo "Caddy reloaded: $HOSTS"
    else
      echo "!! контейнер Caddy chemolymp не найден — сайт подхватится при его перезапуске"
    fi
  else
    rm -f /opt/caddy/sites/egormath.caddy.new
    echo "без изменений: $HOSTS"
  fi
else
  echo "!! EGORMATH_HOSTS пуст или нет /opt/caddy/sites — сайт в Caddy не обновлён"
fi

echo "==> Health"
for _ in $(seq 1 20); do
  if $COMPOSE exec -T egormath-web python /app/deploy/vps/healthcheck.py >/dev/null 2>&1; then
    echo "===== Deploy OK ($(git rev-parse --short HEAD)) ====="
    exit 0
  fi
  sleep 3
done
echo "!! healthz failed"
$COMPOSE logs --tail=50 egormath-web
exit 1
