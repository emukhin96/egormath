# Общее для скриптов deploy/vps/*.sh. Подключается через source.
APP_DIR="${APP_DIR:-/opt/egormath}"
ENV_FILE="$APP_DIR/.env"

# .env — dotenv-файл (его читает docker compose), а не shell-скрипт:
# читаем нужные ключи построчно, как в scripts/deploy.sh chemolymp.
env_get() {
  local line
  line="$(grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%$'\r'}"
  case "$line" in
    \"*\") line="${line#\"}"; line="${line%\"}" ;;
    \'*\') line="${line#\'}"; line="${line%\'}" ;;
  esac
  printf '%s' "$line"
}

DATA_DIR="$(env_get DATA_DIR)"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
export DATA_DIR
export APP_UID="${APP_UID:-$(id -u)}"
# COMPOSE можно подменить из окружения — для прогона скриптов без Docker (тесты на Mac)
COMPOSE="${COMPOSE:-docker compose --env-file $ENV_FILE -f $APP_DIR/deploy/vps/compose.yaml}"
