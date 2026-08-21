# EgorMath — local helpers
# CSS: Tailwind standalone CLI (no Node on the server).

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
	  curl -sL -o "$(TW)" "$(TW_URL)"; \
	  chmod +x "$(TW)"; \
	fi

build-css: ensure-tailwind
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --minify
	@echo "Built $(CSS_OUT)"

watch-css: ensure-tailwind
	"$(TW)" -i "$(CSS_IN)" -o "$(CSS_OUT)" --watch

test:
	cd public_html && $(PYTHON) manage.py test

# Полная проверка перед коммитом: собранный CSS должен совпадать с исходником.
# git diff молчит про untracked-файлы, поэтому сначала проверяем сам факт учёта.
check: build-css test
	@git ls-files --error-unmatch "$(CSS_OUT)" >/dev/null 2>&1 \
	  || { echo "$(CSS_OUT) не под git — добавьте его в коммит"; exit 1; }
	git diff --exit-code -- "$(CSS_OUT)"
	@echo "check: OK"
