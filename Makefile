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

CSS_IN := public_html/static/css/input.css
CSS_OUT := public_html/static/css/app.css
# Стили экранов — по файлу на экран в screens/ (новый экран = новый файл,
# общих строк у параллельных PR нет). Перед сборкой склеиваются в
# _screens.css (не в git), который input.css подключает одной строкой.
SCREENS := $(sort $(wildcard public_html/static/css/screens/*.css))
SCREENS_OUT := public_html/static/css/_screens.css

# В CI venv нет — тогда берётся системный python
PYTHON := $(shell test -x "$(ROOT)venv/bin/python" && echo ../venv/bin/python || echo python)

.PHONY: build-css watch-css ensure-tailwind screens-css test check

# С VPS соединения с CDN GitHub часто глохнут после первых сотен КБ и висят
# без обрыва (так завис деплой 23.10), а нормальная загрузка идёт за секунды.
# Поэтому медленнее 100 КБ/с 10 секунд — обрываем и пробуем снова, до 20 раз.
# Каждая попытка — новый curl: встроенный --retry на сервере проваливал
# 21 попытку подряд, а следующий запуск curl тут же качал файл. Качаем во
# временный файл, чтобы оборванная загрузка не осталась на месте CLI.
ensure-tailwind:
	@mkdir -p "$(TOOLS)"
	@if [ ! -x "$(TW)" ]; then \
	  echo "Downloading Tailwind CLI $(TW_VERSION) ($(TW_ASSET))..."; \
	  ok=; for i in $$(seq 20); do \
	    curl -fsSL --connect-timeout 15 --speed-limit 102400 --speed-time 10 \
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

build-css: ensure-tailwind screens-css
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --minify
	@echo "Built $(CSS_OUT)"

# Правки в screens/*.css при watch не подхватываются: после них — make build-css
watch-css: ensure-tailwind screens-css
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --watch

# Тест collectstatic ждёт собранный app.css
test: build-css
	cd public_html && $(PYTHON) manage.py test

# Полная проверка перед коммитом: CSS собирается из input.css, тесты зелёные.
check: test
	@echo "check: OK"
