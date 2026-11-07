# EgorMath — local helpers
# CSS: Tailwind standalone CLI (no Node on the server).
# app.css не хранится в git (иначе каждый PR с правкой шаблонов конфликтует
# с соседними на однострочном минифицированном файле): локально его собирает
# build-css, на проде — Dockerfile, в CI — workflow.

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
TOOLS := $(ROOT)tools
TW := $(TOOLS)/tailwindcss
TW_VERSION := v4.3.3
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

ifeq ($(UNAME_S),Darwin)
  ifeq ($(UNAME_M),arm64)
    TW_ASSET := tailwindcss-macos-arm64
  else
    TW_ASSET := tailwindcss-macos-x64
  endif
else ifeq ($(UNAME_S),Linux)
  ifeq ($(UNAME_M),aarch64)
    TW_ASSET := tailwindcss-linux-arm64
  else
    TW_ASSET := tailwindcss-linux-x64
  endif
else
  $(error Unsupported OS for Tailwind standalone: $(UNAME_S)/$(UNAME_M))
endif

TW_URL := https://github.com/tailwindlabs/tailwindcss/releases/download/$(TW_VERSION)/$(TW_ASSET)
# Порог обрыва загрузки, байт/с (см. ensure-tailwind). На честно медленном
# канале — make build-css TW_SPEED_LIMIT=0: тогда без обрыва.
TW_SPEED_LIMIT ?= 102400

CSS_IN := public_html/static/css/input.css
CSS_OUT := public_html/static/css/app.css
# Стили экранов — по файлу на экран в screens/ (новый экран = новый файл,
# общих строк у параллельных PR нет). Перед сборкой склеиваются в
# _screens.css (не в git), который input.css подключает одной строкой.
SCREENS := $(sort $(wildcard public_html/static/css/screens/*.css))
SCREENS_OUT := public_html/static/css/_screens.css
# Скрипты base.html, которые нужны каждой странице, склеиваются в один
# app.js (не в git, как app.css): один запрос вместо одиннадцати. Порядок —
# как раньше стояли теги <script defer>: math.js до остальных (renderMathContent).
JS_DIR := public_html/static/js
JS_BASE := math katex_copy autosave image_paste livefile busy shell dialogs quick_clone image_zoom taxonomy
JS_FILES := $(addprefix $(JS_DIR)/,$(addsuffix .js,$(JS_BASE)))
JS_OUT := $(JS_DIR)/app.js

# В CI venv нет — тогда берётся системный python
PYTHON := $(shell test -x "$(ROOT)venv/bin/python" && echo ../venv/bin/python || echo python)

.PHONY: build-css build-js watch-css watch-js ensure-tailwind screens-css test check

# С VPS соединения с CDN GitHub часто глохнут после первых сотен КБ и висят
# без обрыва (так завис деплой 23.10), а нормальная загрузка идёт за секунды.
# Заглохшее соединение — не ноль, а струйка 14–32 КБ/с, поэтому порог
# TW_SPEED_LIMIT по умолчанию 100 КБ/с: медленнее 10 секунд — обрываем и
# пробуем снова, до 20 раз. Каждая попытка — новый curl: встроенный --retry
# на сервере проваливал 21 попытку подряд, а следующий запуск curl тут же
# качал файл. Качаем во временный файл, чтобы оборванная загрузка не
# осталась на месте CLI.
ensure-tailwind:
	@mkdir -p "$(TOOLS)"
	@if [ ! -x "$(TW)" ]; then \
	  echo "Downloading Tailwind CLI $(TW_VERSION) ($(TW_ASSET))..."; \
	  ok=; for i in $$(seq 20); do \
	    curl -fsSL --connect-timeout 15 --speed-limit $(TW_SPEED_LIMIT) --speed-time 10 \
	      -o "$(TW).part" "$(TW_URL)" && { ok=1; break; }; \
	    sleep 2; \
	  done; \
	  if [ -z "$$ok" ]; then \
	    rm -f "$(TW).part"; echo "Tailwind CLI download failed after 20 attempts" >&2; exit 1; \
	  fi; \
	  chmod +x "$(TW).part" && mv "$(TW).part" "$(TW)"; \
	fi

screens-css:
	@cat $(SCREENS) /dev/null > "$(SCREENS_OUT)"

build-css: ensure-tailwind screens-css build-js
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --minify
	@echo "Built $(CSS_OUT)"

# Склейка без минификации и без Node: между файлами «;» на отдельной строке,
# чтобы IIFE соседей не слиплись в вызов. Каждый файл — замыкание или
# глобальные функции, как при отдельных тегах, поведение не меняется.
build-js: $(JS_FILES)
	@{ echo "/* Собрано make build-js из: $(JS_BASE). Не править руками. */"; \
	   for f in $(JS_FILES); do echo; echo "/* === $$f === */"; cat "$$f"; echo; echo ";"; done; } > "$(JS_OUT)"
	@echo "Built $(JS_OUT)"

# Правки в screens/*.css при watch не подхватываются: после них — make build-css
watch-css: ensure-tailwind screens-css build-js
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --watch

# Пересборка app.js при правке склеиваемых скриптов (runserver отдаёт только
# app.js): опрос раз в 2 с, без inotify и Node. Запускать во втором
# терминале рядом с watch-css; Ctrl-C — выход. Отпечаток — по содержимому
# файлов: время в ls -l с точностью до минуты пропускало правку той же длины.
watch-js: build-js
	@echo "watch-js: слежу за $(JS_BASE)"
	@last=""; while :; do now=$$(cat $(JS_FILES) | cksum); \
	  if [ "$$now" != "$$last" ]; then last=$$now; $(MAKE) --no-print-directory build-js; fi; \
	  sleep 2; done

# Тест collectstatic ждёт собранный app.css
test: build-css
	cd public_html && $(PYTHON) manage.py test

# Полная проверка перед коммитом: CSS собирается из input.css, тесты зелёные.
check: test
	@echo "check: OK"
