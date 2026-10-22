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

# В CI venv нет — тогда берётся системный python
PYTHON := $(shell test -x "$(ROOT)venv/bin/python" && echo ../venv/bin/python || echo python)

.PHONY: build-css watch-css ensure-tailwind test check

ensure-tailwind:
	@mkdir -p "$(TOOLS)"
	@if [ ! -x "$(TW)" ]; then \
	  echo "Downloading Tailwind CLI $(TW_VERSION) ($(TW_ASSET))..."; \
	  curl -fsSL -o "$(TW)" "$(TW_URL)"; \
	  chmod +x "$(TW)"; \
	fi

build-css: ensure-tailwind
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --minify
	@echo "Built $(CSS_OUT)"

watch-css: ensure-tailwind
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --watch

# Тест collectstatic ждёт собранный app.css
test: build-css
	cd public_html && $(PYTHON) manage.py test

# Полная проверка перед коммитом: CSS собирается из input.css, тесты зелёные.
check: test
	@echo "check: OK"
