#!/usr/bin/env bash
###############################################################################
# Пакеты и шрифты egormath → общий latex-api на этом же сервере:
#   /opt/egormath/deploy/vps/latex-files.sh        (вызывает и deploy.sh)
#
# worksheets/tex/*.sty      → /opt/latex-api/data/assets/egormath/
#                             (в контейнере /opt/latex-api/assets, TEXINPUTS)
# worksheets/tex/fonts/*    → /opt/latex-api/data/fonts/egormath/
#                             (fontconfig и OSFONTDIR контейнера)
#
# Листки подключают \usepackage{egor} и \usepackage{egorweb}, презентации —
# egorbeamer; шрифты Inter и STIX Two ищутся по имени файла. В запросе к API
# идут только картинки задач (лимит — 20 файлов), поэтому без этого шага
# новые листки не соберутся. latex-api перезапускать не нужно: файлы читаются
# при каждой сборке.
###############################################################################
set -euo pipefail

source "$(dirname "$(readlink -f "$0")")/lib.sh"
cd "$APP_DIR"

LATEX_DATA="${LATEX_API_DATA:-/opt/latex-api/data}"
SRC=public_html/worksheets/tex
STY_DIR="$LATEX_DATA/assets/egormath"
FONT_DIR="$LATEX_DATA/fonts/egormath"

# Файлы видит только общий latex-api этого сервера. Если сайт ещё ходит на
# старый API (deploy/VPS.md §5a), egorweb.sty там нет — пусть сайт шлёт
# пакеты сам (LATEX_SEND_STY=1), иначе новые листки не соберутся.
setting() {  # значение из data/secrets/<имя> (как read_secret в settings.py)
  if [ -f "$DATA_DIR/secrets/$1" ]; then tr -d '[:space:]' < "$DATA_DIR/secrets/$1"; fi
}
api_url="$(setting LATEX_API_URL)"
send_sty="$(setting LATEX_SEND_STY)"
case "$api_url" in
  http://latex-api:8000*|https://latex.emukhin.ru*) ;;
  *)
    if [ "$send_sty" != 1 ]; then
      echo "!! LATEX_API_URL=${api_url:-<умолчание settings.py>} — не общий latex-api этого сервера,"
      echo "   а LATEX_SEND_STY не включён: листки не найдут egorweb.sty."
      echo "   Переключитесь на общий latex-api (deploy/VPS.md §5a) или временно:"
      echo "   echo 1 > $DATA_DIR/secrets/LATEX_SEND_STY  (шрифты Inter/STIX тогда нужны на старом API)"
      exit 1
    fi
    ;;
esac

for dir in "$LATEX_DATA/assets" "$LATEX_DATA/fonts"; do
  if [ ! -d "$dir" ] || [ ! -w "$dir" ]; then
    echo "!! нет каталога $dir или прав на запись в него (latex-api развёрнут?)"
    exit 1
  fi
done

# TEXINPUTS обходит assets// целиком: одноимённый пакет в другой папке
# сделал бы выбор версии случайным. Чужие копии не удаляем — сообщаем.
dups=""
for path in "$SRC"/*.sty; do
  name="$(basename "$path")"
  other="$(find "$LATEX_DATA/assets" -name "$name" ! -path "$STY_DIR/$name" 2>/dev/null || true)"
  [ -n "$other" ] && dups="$dups $other"
done
if [ -n "$dups" ]; then
  echo "!! в $LATEX_DATA/assets есть другие копии наших пакетов:$dups"
  echo "   Уберите их (или перенесите в $STY_DIR) и повторите."
  exit 1
fi

mkdir -p "$STY_DIR" "$FONT_DIR"
changed=0
copy() {  # copy <файл> <каталог>: только изменившиеся, права 644 для latexapi
  local dst="$2/$(basename "$1")"
  if ! cmp -s "$1" "$dst"; then
    install -m 644 "$1" "$dst"
    echo "   $(basename "$1")"
    changed=$((changed + 1))
  fi
}
for path in "$SRC"/*.sty; do copy "$path" "$STY_DIR"; done
for path in "$SRC"/fonts/*; do copy "$path" "$FONT_DIR"; done
echo "LaTeX files: обновлено $changed (пакеты — $STY_DIR, шрифты — $FONT_DIR)"
