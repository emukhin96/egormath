#!/usr/bin/env bash
# Пуш ветки и pull request через токен из .secrets/GITHUB_TOKEN — для агентов
# (Claude, Codex), у которых нет SSH-ключа. Умеет только то, что разрешено
# пайплайном (docs/PIPELINE.md, раздел 5): запушить ветку, открыть PR в main,
# показать состояние PR и замечания ревью. Merge, rebase, force-push и правка
# main здесь намеренно отсутствуют — слияние делает только человек, вручную.
#
#   tools/pr.sh push                          текущую ветку → GitHub (fast-forward only)
#   tools/pr.sh open "Заголовок" [body.md] [база]   PR ветка → main (или показать уже открытый);
#                                             база — ветка другого PR, если это стек
#   tools/pr.sh status                        PR текущей ветки: состояние, CI, замечания ревью (с id)
#   tools/pr.sh reply <id> "Текст"            ответить в треде замечания (id — из status)
#
# Токен: fine-grained PAT на один репозиторий, права Contents: read/write,
# Pull requests: read/write. Файл в .gitignore; скрипт его никогда не печатает.
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
REPO=emukhin96/egormath
API="https://api.github.com/repos/$REPO"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

die() { echo "pr.sh: $*" >&2; exit 1; }

# .secrets лежит рядом с основным .git — из git worktree тоже находится
MAIN_ROOT=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
if [ -n "${GITHUB_TOKEN:-}" ]; then
  TOKEN=$GITHUB_TOKEN
elif [ -r "$ROOT/.secrets/GITHUB_TOKEN" ]; then
  TOKEN=$(tr -d '[:space:]' < "$ROOT/.secrets/GITHUB_TOKEN")
elif [ -r "$MAIN_ROOT/.secrets/GITHUB_TOKEN" ]; then
  TOKEN=$(tr -d '[:space:]' < "$MAIN_ROOT/.secrets/GITHUB_TOKEN")
else
  die "нет токена: положите его в .secrets/GITHUB_TOKEN или в переменную GITHUB_TOKEN"
fi
[ -n "$TOKEN" ] || die "файл .secrets/GITHUB_TOKEN пуст"

[ "$BRANCH" != "main" ] && [ "$BRANCH" != "HEAD" ] || die "работаем только из ветки, не из main (текущая: $BRANCH)"

mask() { sed "s#$TOKEN#***#g"; }

api() { # api METHOD /path [curl-args…]
  local method=$1 path=$2; shift 2
  curl -sS -X "$method" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$@" "$API$path"
}

pr_json() { api GET "/pulls?head=emukhin96:$BRANCH&state=open&per_page=1"; }

cmd_push() {
  [ $# -eq 0 ] || die "push не принимает аргументов (force-push запрещён)"
  # Ветка, PR которой уже слит, в GitHub удалена — пуш воссоздал бы её заново.
  if ! git ls-remote --exit-code -q "https://x-access-token:${TOKEN}@github.com/$REPO.git" "refs/heads/$BRANCH" >/dev/null 2>&1; then
    local merged
    merged=$(api GET "/pulls?head=emukhin96:$BRANCH&state=closed&per_page=5" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(" ".join("#%s" % p["number"] for p in d if p.get("merged_at")) if isinstance(d, list) else "")')
    [ -z "$merged" ] || die "PR $merged для ветки $BRANCH уже слит и ветка удалена — новые правки идут новой веткой от main"
  fi
  echo "push $BRANCH → $REPO"
  git push "https://x-access-token:${TOKEN}@github.com/$REPO.git" \
    "refs/heads/$BRANCH:refs/heads/$BRANCH" 2>&1 | mask
}

cmd_open() {
  local title=${1:-} body=${2:-} base=${3:-main}
  [ -n "$title" ] || die "нужен заголовок: tools/pr.sh open \"Заголовок\" [body.md] [база]"
  [ -z "$body" ] || [ -r "$body" ] || die "файл с описанием не найден: $body"
  local existing
  existing=$(pr_json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["html_url"] if isinstance(d, list) and d else "")')
  if [ -n "$existing" ]; then echo "PR для $BRANCH уже открыт: $existing"; return 0; fi
  git ls-remote --exit-code -q "https://x-access-token:${TOKEN}@github.com/$REPO.git" "refs/heads/$BRANCH" >/dev/null 2>&1 \
    || die "ветка $BRANCH ещё не в GitHub — сначала tools/pr.sh push"
  local payload
  payload=$(mktemp)
  python3 - "$title" "$body" "$BRANCH" "$base" > "$payload" <<'PY'
import json, sys
title, body, head, base = sys.argv[1:5]
text = open(body, encoding='utf-8').read() if body else ''
print(json.dumps({'title': title, 'body': text, 'head': head, 'base': base}))
PY
  api POST /pulls --data "@$payload" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "html_url" in d: print("PR #%s открыт: %s" % (d["number"], d["html_url"]))
else: print("GitHub: %s %s" % (d.get("message"), d.get("errors", ""))); sys.exit(1)'
  rm -f "$payload"
}

cmd_status() {
  local num
  num=$(pr_json | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not (isinstance(d, list) and d): sys.exit(0)
pr = d[0]
print("PR #%s %s [%s] %s" % (pr["number"], pr["title"], pr["state"], pr["html_url"]), file=sys.stderr)
print("ветка %s → %s, head %s%s" % (pr["head"]["ref"], pr["base"]["ref"], pr["head"]["sha"][:7], ", draft" if pr["draft"] else ""), file=sys.stderr)
print(pr["number"])')
  if [ -z "$num" ]; then echo "открытого PR для ветки $BRANCH нет"; return 0; fi
  api GET "/pulls/$num/reviews?per_page=100" | python3 -c '
import json, sys
for r in json.load(sys.stdin):
    if r["state"] != "COMMENTED" or (r.get("body") or "").strip():
        print("ревью: %s — %s %s" % (r["user"]["login"], r["state"], (r.get("body") or "")[:120].replace("\n", " ")))'
  api GET "/pulls/$num/comments?per_page=100" | python3 -c '
import json, sys
cs = json.load(sys.stdin)
print("замечаний в коде: %d" % len(cs))
for c in cs:
    tag = "    ↳" if c.get("in_reply_to_id") else "  #%s" % c["id"]
    print("%s %s %s:%s — %s" % (tag, c["user"]["login"], c["path"], c.get("line") or c.get("original_line"), c["body"].strip().splitlines()[0][:110]))'
  api GET "/issues/$num/comments?per_page=100" | python3 -c '
import json, sys
cs = json.load(sys.stdin)
if cs: print("комментариев к PR: %d (последний от %s)" % (len(cs), cs[-1]["user"]["login"]))'
  api GET "/commits/$(git rev-parse HEAD)/check-runs" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "check_runs" not in d:
    print("CI: статус недоступен (токену нужно право Checks: read) — смотрите вкладку Checks в PR")
for c in d.get("check_runs", []):
    print("CI: %s — %s" % (c["name"], c.get("conclusion") or c["status"]))'
}

cmd_reply() {
  local id=${1:-} text=${2:-}
  [[ "$id" =~ ^[0-9]+$ ]] || die "нужен числовой id замечания (tools/pr.sh status)"
  [ -n "$text" ] || die "нужен текст ответа"
  local num
  num=$(pr_json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["number"] if isinstance(d, list) and d else "")')
  [ -n "$num" ] || die "открытого PR для ветки $BRANCH нет"
  local payload
  payload=$(mktemp)
  python3 -c 'import json,sys; print(json.dumps({"body": sys.argv[1]}))' "$text" > "$payload"
  api POST "/pulls/$num/comments/$id/replies" --data "@$payload" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "html_url" in d: print("ответ опубликован: %s" % d["html_url"])
else: print("GitHub: %s" % d.get("message")); sys.exit(1)'
  rm -f "$payload"
}

case "${1:-}" in
  push)   shift; cmd_push "$@" ;;
  open)   shift; cmd_open "$@" ;;
  status) shift; cmd_status ;;
  reply)  shift; cmd_reply "$@" ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
