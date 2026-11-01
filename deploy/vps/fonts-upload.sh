#!/usr/bin/env bash
###############################################################################
# Лицензионные шрифты (SchoolBookC, TextBookC) с Mac → latex-api на VPS.
#   deploy/vps/fonts-upload.sh            (запускать на Mac, из корня репозитория)
#   VPS=root@77.232.132.139 deploy/vps/fonts-upload.sh
#
# Шрифты ParaType коммерческие, а репозиторий публичный — в git их класть
# нельзя (в tex/fonts только OFL: Inter, STIX Two). Поэтому они живут на
# сервере в $DATA_DIR/fonts (/opt/egormath/data/fonts): latex-files.sh при
# каждом деплое копирует оттуда в /opt/latex-api/data/fonts/egormath рядом
# с шрифтами из репозитория. Этот скрипт кладёт файлы в обе папки сразу —
# font=school собирается без деплоя, latex-api перезапускать не нужно.
###############################################################################
set -euo pipefail

VPS="${VPS:-chemolymp-demo}"
FONTS_SRC="${FONTS_SRC:-$HOME/Library/Fonts}"
REMOTE_DATA="${REMOTE_DATA:-/opt/egormath/data/fonts}"
REMOTE_LATEX="${REMOTE_LATEX:-/opt/latex-api/data/fonts/egormath}"

shopt -s nullglob
files=("$FONTS_SRC"/SchoolBookC*.ttf "$FONTS_SRC"/TextBookC*.ttf)
if [ ${#files[@]} -eq 0 ]; then
  echo "!! в $FONTS_SRC нет SchoolBookC*.ttf / TextBookC*.ttf (FONTS_SRC=…)" >&2
  exit 1
fi

echo "==> ${#files[@]} файлов → $VPS:$REMOTE_DATA"
ssh "$VPS" "mkdir -p '$REMOTE_DATA'"
scp -q "${files[@]}" "$VPS:$REMOTE_DATA/"

echo "==> $REMOTE_DATA → $REMOTE_LATEX"
ssh "$VPS" "set -e; mkdir -p '$REMOTE_LATEX'
  for f in '$REMOTE_DATA'/*.ttf '$REMOTE_DATA'/*.otf; do
    if [ -e \"\$f\" ]; then install -m 644 \"\$f\" '$REMOTE_LATEX/'; fi
  done
  ls '$REMOTE_LATEX' | grep -iE 'SchoolBook|TextBook'"
echo "Готово: font=school в редакторе PDF должен собираться."
