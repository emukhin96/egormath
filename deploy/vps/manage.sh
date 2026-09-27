#!/usr/bin/env bash
# manage.py в работающем контейнере: deploy/vps/manage.sh <команда> [аргументы]
#   deploy/vps/manage.sh createsuperuser
#   deploy/vps/manage.sh cleanup_work_activity
set -euo pipefail
source "$(dirname "$0")/lib.sh"
TTY=-T
[ -t 0 ] && [ -t 1 ] && TTY=
exec $COMPOSE exec $TTY egormath-web python manage.py "$@"
