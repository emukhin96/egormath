#!/usr/bin/env bash
# Сводка по логу доступа egormath-web: deploy/vps/log-report.sh [период]
#   deploy/vps/log-report.sh          # за 7 дней
#   deploy/vps/log-report.sh 24h      # за сутки
# Docker хранит логи контейнера с ротацией (20 МБ × 5), поэтому очень
# старые дни могут не попасть. Пересоздание контейнера (deploy.sh) логи
# обнуляет — сводку до деплоя лучше снять заранее (cron — crontab.example).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
SINCE="${1:-168h}"
CID="$($COMPOSE ps -q egormath-web)"
[ -n "$CID" ] || { echo "egormath-web не запущен" >&2; exit 1; }
docker logs --timestamps --since "$SINCE" "$CID" 2>&1 | python3 "$APP_DIR/deploy/vps/log_report.py"
