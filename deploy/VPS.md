# egormath на VPS (общий сервер с chemolymp)

Сервер — Timeweb Cloud-50 `77.232.132.139` (демо-сервер chemolymp, Ubuntu 24.04,
2 vCPU / 4 ГБ). На нём всё в Docker: стек chemolymp (`/opt/chemolymp`, его Caddy
держит 80/443), общий latex-api (`/opt/latex-api`, ADR-003 chemolymp) и стек
egormath (`/opt/egormath`, этот документ). SSH: `ssh chemolymp-demo` (пользователь
`deploy`, группа `docker`) или `ssh root@77.232.132.139`.

Старый прод на Timeweb shared — [DEPLOY.md](DEPLOY.md), до окончания переезда.

## Как устроено

```
браузер ─HTTPS─> Caddy chemolymp ─(сеть edge)─> egormath-front ──> egormath-web ──> egormath-db
                 /opt/caddy/sites/egormath.caddy   Caddy: /static/, /live/   gunicorn     MySQL 8
```

| Сервис | Что делает |
|---|---|
| `egormath-web` | образ из `Dockerfile` (Python 3.12), gunicorn gthread 2×4, `timeout 180` (`deploy/vps/gunicorn.conf.py`) |
| `egormath-front` | `caddy:2-alpine`: `/static/` и `/live/*.txt` с диска без Django, остальное — в web (`deploy/vps/Caddyfile.front`) |
| `egormath-db` | `mysql:8.0`, порт не публикуется, 256 МБ buffer pool (`deploy/vps/mysql.cnf`) |

Данные — в `/opt/egormath/data/` (bind-mount, не в git):

| Каталог | В контейнере | Что это |
|---|---|---|
| `secrets/` | `/app/.secrets` | те же файлы, что `.secrets/` на Timeweb |
| `media/` | `/app/media` | фото решений, кэш PDF |
| `live/` | `/app/public_html/live` | файлы-версии живых страниц |
| `staticfiles/` | `/app/public_html/staticfiles` | результат `collectstatic` |
| `var/`, `cache/` | `/app/var`, `/app/.cache` | корпус, партии; файловый кэш рубрикатора |
| `mysql/` | `/var/lib/mysql` | база |
| `backups/`, `logs/` | — | наборы бэкапа (раздел «Бэкапы») и логи cron |

Настройки стека — `/opt/egormath/.env` (образец — `deploy/vps/env.example`).

Имена сервисов начинаются с `egormath-` не для красоты: `web` и `front` состоят в
общей сети `edge`, где их видит Caddy chemolymp. Сервис `web` в этой сети
перехватил бы запросы chemolymp (его Caddy ходит на `web:8000`).

## Повседневное

| Задача | Команда (на сервере от `deploy`) |
|---|---|
| Деплой `main` | `/opt/egormath/deploy/vps/deploy.sh` (с Mac: `ssh chemolymp-demo /opt/egormath/deploy/vps/deploy.sh`) |
| Деплой ветки/тега | `/opt/egormath/deploy/vps/deploy.sh <ref>` |
| manage.py | `/opt/egormath/deploy/vps/manage.sh <команда>` |
| Логи | `cd /opt/egormath && docker compose --env-file .env -f deploy/vps/compose.yaml logs -f --tail=100 egormath-web` |
| Состояние, память | `docker compose … ps`, `docker stats --no-stream` |
| Бэкап вручную | `/opt/egormath/deploy/vps/backup.sh` |
| Откат базы/файлов на ночной слепок | `/opt/egormath/deploy/vps/restore.sh --stamp <YYYYMMDD-HHMMSS>` (см. «Восстановление после потери сервера») |
| Сводка нагрузки | `/opt/egormath/deploy/vps/log-report.sh` (7 дней) или `… 24h`; еженедельно — `data/logs/weekly-report.log` |
| Выключить холст | `echo 0 > /opt/egormath/data/secrets/CANVAS_ENABLED` и `docker compose … restart egormath-web` |

`deploy.sh`: fetch → checkout → сборка образа → бэкап → `check --deploy` →
`migrate` → `seed_rubricator` → `collectstatic` → пересоздание контейнеров →
`/opt/caddy/sites/egormath.caddy` из шаблона + `caddy reload` → `/healthz`.
Пока пересоздаётся `egormath-web`, `egormath-front` держит запросы до 20 с —
пользователи видят паузу, а не 502.

Время ответа каждого запроса — в логе `egormath-web` (последнее поле, `…ms`).

## Бэкапы вне сервера и мониторинг

`backup.sh` каждую ночь (cron, 01:15 UTC) кладёт в `/opt/egormath/data/backups`
набор с одной отметкой времени и копирует его в S3 Timeweb (rclone,
`BACKUP_RCLONE_REMOTE`):

| Файл | Что внутри |
|---|---|
| `db-<stamp>.sql.gz` | дамп MySQL (`--single-transaction --routines`) |
| `media-<stamp>.tar.gz` | `data/media`: картинки задач, фото решений, кэш PDF |
| `var-<stamp>.tar.gz` | `data/var`: корпус листков и партии задачников, ещё не загруженные в каталог |
| `secrets-<stamp>.tar.gz.enc` | `data/secrets`, `.env`, `crontab -l`, `rclone.conf` — AES-256 паролем `BACKUP_SECRETS_PASSPHRASE` |

На диске и в S3 хранится `RETENTION_DAYS` (14) дней; в S3 бессрочно остаются
дампы базы за 1-е число месяца и дампы Timeweb (`timeweb*.sql.gz`).
Без пароля секретов архив не создаётся (скрипт пишет `!!` в
`data/logs/backup.log`) — и после потери сервера пропадут `DJANGO_SECRET_KEY`
(сессии, токены форм), ключи API и `.env`.

Включается один раз:

1. S3: Панель Timeweb → S3-хранилище → приватный бакет `egormath-backups`,
   ключи доступа (Access Key / Secret Key). На сервере от root:
   `apt-get install -y rclone`; от `deploy`: `rclone config` → `n` → имя `s3`
   → тип `s3` → provider `Other` → ключи → endpoint `https://s3.twcstorage.ru`.
   Проверка: `rclone lsd s3:`. В `.env`: `BACKUP_RCLONE_REMOTE=s3:egormath-backups`.
   (Сделано 27.09.2026.)
2. Пароль секретов — на сервере и на Mac, значение одно и то же:

   ```bash
   # на сервере, от deploy
   P=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
   echo "BACKUP_SECRETS_PASSPHRASE=$P" >> /opt/egormath/.env
   # на Mac, из корня репозитория: то же значение в .secrets/
   ssh chemolymp-demo "grep ^BACKUP_SECRETS_PASSPHRASE= /opt/egormath/.env | cut -d= -f2-" \
     > .secrets/BACKUP_SECRETS_PASSPHRASE && chmod 600 .secrets/BACKUP_SECRETS_PASSPHRASE
   ```

   Пароль нужен только при восстановлении: на новом сервере его вписывают
   в `.env` с Mac. Потерять пароль = потерять секреты, поэтому копия ещё и в
   менеджере паролей.
3. Тревога, если бэкап перестал проходить: чек на Healthchecks.io (период
   1 день, льгота 2 ч), его URL — в `.env`: `BACKUP_PING_URL=…`. Пинг уходит
   только после успешного `backup.sh`; молчание = письмо.
4. Проверка: `/opt/egormath/deploy/vps/backup.sh` — четыре файла и строка
   `==> rclone -> s3:egormath-backups`; `rclone ls s3:egormath-backups`.

**Раз в месяц** — репетиция восстановления из копии вне сервера, на Mac:

```bash
tools/stage.sh --s3     # ~1–2 мин: набор из S3 → локальный MySQL + media, расшифровка архива секретов
```

Успех — строка «(из копии в S3: набор … восстановился)» и
«==> архив секретов расшифрован: …» без `!!`; затем открыть стенд
(`--run`, http://127.0.0.1:8003) и посмотреть дашборд и базу задач.
Полное восстановление с нуля — раздел «Восстановление после потери сервера».

Мониторинг снаружи — любой бесплатный сервис проверки доступности
(UptimeRobot, Healthchecks.io, BetterStack): HTTP-проверка
`https://math.emukhin.ru/healthz` раз в 5 минут, ожидается код 200 и текст
`"db": "ok"`; оповещение на почту или в Telegram.

Решение о масштабировании — по недельной сводке `log-report.sh`
(понедельник, `data/logs/weekly-report.log`): если в учебные часы p95
тяжёлых страниц держится выше 1 с или «в среднем занято потоков»
подходит к числу ядер, пора на отдельный сервер (разбор «egormath при
кратном росте», ступень 1). Логи контейнера обнуляются при его
пересоздании (`deploy.sh`), поэтому сводка по расписанию надёжнее ручной.

## Восстановление после потери сервера

Репетиция 30.09.2026 (набор из S3 → Mac): база 3 МБ заливается за 3 с, все
6657 ссылок на файлы из базы нашлись в `media-*.tar.gz`, миграции совпали с
`main`, страницы учителя и ученика открываются. Что нужно иметь вне сервера:

| Что | Где |
|---|---|
| Код | GitHub `emukhin96/egormath`, ветка `main` (прод всегда на `origin/main`) |
| База, media, var, секреты | S3 Timeweb, бакет `egormath-backups` (ключи — в панели Timeweb) |
| Пароль архива секретов | Mac, `.secrets/BACKUP_SECRETS_PASSPHRASE` (и менеджер паролей) |
| DNS `math.emukhin.ru` | панель Timeweb → Домены |
| Всё остальное | воссоздаётся: `.env` (новые пароли MySQL), deploy key GitHub, crontab (`crontab.example`), `staticfiles`, `live/`, кэш |

Сервер общий: сначала поднимается стек chemolymp (Caddy на 80/443, сеть
`edge`, `/opt/caddy/sites`) и общий latex-api по их RUNBOOK / ADR-003 —
без них у egormath нет HTTPS и сборки PDF. `LATEX_API_KEY` в восстановленных
секретах — от старого latex-api; после его переустановки повторить §5a.

Теряется всё после последнего ночного дампа (до суток): выдачи, ответы,
доски, фото за день. Если `DJANGO_SECRET_KEY` восстановлен из архива,
сессии и ссылки `/s/<token>/` живы; если нет — всех разлогинит, а
`livefile` сгенерирует новые имена файлов сам.

Порядок (по разделу «Первичная установка», отличия — здесь):

1. §1 от root; дополнительно `apt-get install -y rclone`.
2. §2 — новый deploy key к репозиторию, `git clone … /opt/egormath`.
3. `rclone config` с ключами S3 из панели Timeweb (как в «Бэкапы», п. 1),
   проверка: `rclone ls s3:egormath-backups`.
4. `.env` из `deploy/vps/env.example`: новые `MYSQL_PASSWORD` /
   `MYSQL_ROOT_PASSWORD` (старые не нужны — дамп несёт данные, а не
   пользователей MySQL), `EGORMATH_HOSTS`, `BACKUP_RCLONE_REMOTE=s3:egormath-backups`,
   `BACKUP_SECRETS_PASSPHRASE` — с Mac.
5. Восстановление одной командой:

   ```bash
   /opt/egormath/deploy/vps/restore.sh                            # самый свежий набор из S3
   /opt/egormath/deploy/vps/restore.sh --stamp 20260929-011501    # конкретный набор
   ```

   Скрипт скачивает набор во временный `data/restore-<stamp>/` (не в
   `data/backups`: его чистит по возрасту файлов `backup.sh`, который
   `import-db.sh` запускает перед заливкой), расшифровывает секреты в
   `data/secrets` (только если каталог пуст), заливает базу (`import-db.sh`, с таблицами часовых
   поясов), распаковывает media и var и запускает `deploy.sh` (образ,
   `check --deploy`, миграции, `collectstatic`, контейнеры, сайт в Caddy).
   Старые `.env` и crontab лежат в `data/restored-secrets-<stamp>/` — сверить
   и удалить каталог.
6. `crontab -e` — строки из `deploy/vps/crontab.example`.
7. DNS: A-запись `math` → IP нового сервера.
8. Проверить: `https://math.emukhin.ru/healthz` → `"db": "ok"`, вход, база
   задач, PDF листка (latex-api), фото решения; следующей ночью — что
   `backup.sh` прошёл (`data/logs/backup.log`, Healthchecks).

Откат на ночной слепок на работающем сервере — тот же `restore.sh --stamp …`:
перед заливкой `import-db.sh` сам снимает текущий бэкап; на вопрос про
непустые `media`/`var` можно ответить `N` (архивы только дописывают файлы,
ничего не удаляют).

## Первичная установка

### 1. От root, один раз

```bash
ssh root@77.232.132.139
# swap: без него пик памяти любого стека кончается OOM-killer'ом
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf && sysctl -w vm.swappiness=10
install -d -o deploy -g deploy /opt/egormath
```

### 2. Доступ к репозиторию (от `deploy`)

Ключ `~/.ssh/id_ed25519` уже привязан к репозиторию chemolymp, а GitHub не даёт
привязать один deploy key к двум репозиториям — нужен второй:

```bash
ssh chemolymp-demo
ssh-keygen -t ed25519 -N "" -C egormath-demo-server -f ~/.ssh/egormath_deploy
cat >> ~/.ssh/config <<'CFG'
Host github.com-egormath
  HostName github.com
  User git
  IdentityFile ~/.ssh/egormath_deploy
  IdentitiesOnly yes
CFG
cat ~/.ssh/egormath_deploy.pub
# → GitHub: emukhin96/egormath → Settings → Deploy keys → Add (без write access)
git clone git@github.com-egormath:emukhin96/egormath.git /opt/egormath
```

### 3. Настройки и секреты

```bash
cd /opt/egormath
cp deploy/vps/env.example .env && chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # → MYSQL_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # → MYSQL_ROOT_PASSWORD
nano .env
mkdir -p data/secrets && chmod 700 data/secrets
```

Секреты — **копией `.secrets/` с Timeweb целиком** (с Mac, через него):

```bash
# на Mac
scp -r cs13661@vh426.timeweb.ru:/home/c/cs13661/egormath/.secrets /tmp/egormath-secrets
scp /tmp/egormath-secrets/* chemolymp-demo:/opt/egormath/data/secrets/
rm -rf /tmp/egormath-secrets
```

`DJANGO_SECRET_KEY` оставить прежним: на нём держатся сессии (никого не
разлогинит) и HMAC-имена файлов `live/`. На сервере поправить:

| Файл в `data/secrets/` | Значение |
|---|---|
| `ALLOWED_HOSTS` | `math.emukhin.ru,math.egor.am,vps.math.emukhin.ru` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` | удалить — приходят из `.env` через compose |
| `LATEX_API_URL` | внутренний адрес общего latex-api в сети `edge` (см. п. 5) |
| `LATEX_API_KEY` | ключ `egormath:` из `/opt/latex-api/.env` |
| `GEMINI_API_BASE`, `GEMINI_PROXY_SECRET` | обязательны: сервер в РФ, напрямую Gemini отвечает `User location is not supported` |

`chmod 600 data/secrets/*`.

### 4. Первый запуск

```bash
/opt/egormath/deploy/vps/deploy.sh
crontab -e   # строки из deploy/vps/crontab.example
```

На пустой базе `deploy.sh` создаст таблицы; данные — из дампа Timeweb (ниже).
Проверить таблицы часовых поясов MySQL (без них `__date`-выборки дают NULL):
`import-db.sh` печатает `tz_check`, он не должен быть `NULL`.

### 5. LaTeX API

Общий latex-api (ADR-003 chemolymp) сохранил эндпоинт egormath
`/api/v1/compile-latex` (xelatex × 2 + `assets`). Имя его контейнера в сети
`edge`: `docker network inspect edge --format '{{range .Containers}}{{.Name}} {{end}}'`.
Проверка из контейнера egormath:

```bash
cd /opt/egormath
docker compose --env-file .env -f deploy/vps/compose.yaml exec egormath-web \
  python -c "import requests; print(requests.get('http://latex-api:8000/health', timeout=5).text)"
```

Перед переключением прогнать проверки из [DEPLOY.md](DEPLOY.md) §1.5–1.6a против
нового адреса: колонтитул `2/2`, картинка `\taskpic`, Beamer, шрифты CMU и
SchoolBook. Если чего-то не хватает — это правится в репозитории latex-api.

### 5a. Переключение на общий latex-api (после проверок)

Клиент повторяет запрос, если latex-api занят (503/429 с `Retry-After`,
до 4 повторов и 30 с ожидания — `LATEX_API_RETRIES`, `…_MAX_DELAY`,
`…_BUDGET`), так что очередь сборок сертификатов chemolymp не превращается
у учителя в ошибку.

```bash
# на сервере, от deploy
cd /opt/egormath
C="docker compose --env-file .env -f deploy/vps/compose.yaml"
# latex-api виден из egormath-web по имени в сети edge?
$C exec -T egormath-web python -c "import requests; print(requests.get('http://latex-api:8000/health', timeout=5).text)"
# сохранить старые настройки для отката
cd data/secrets && cp LATEX_API_URL LATEX_API_URL.old && cp LATEX_API_KEY LATEX_API_KEY.old
echo "http://latex-api:8000" > LATEX_API_URL
grep '^LATEX_API_KEYS=' /opt/latex-api/.env | tr ',' '\n' | grep -o 'egormath:.*' | cut -d: -f2- | tr -d '"' > LATEX_API_KEY
test -s LATEX_API_KEY && chmod 600 LATEX_API_URL LATEX_API_KEY && cd /opt/egormath && $C restart egormath-web
```

Проверка: собрать PDF листка с картинкой и презентацию. Откат —
`mv LATEX_API_URL.old LATEX_API_URL; mv LATEX_API_KEY.old LATEX_API_KEY` в
`data/secrets` и `restart egormath-web`.

## Переезд с Timeweb

### Репетиция (сайт на Timeweb работает)

1. DNS (Timeweb → Домены → emukhin.ru): A-запись `vps.math` → `77.232.132.139`.
   В `.env` `EGORMATH_HOSTS=vps.math.emukhin.ru`.
2. Дамп на Timeweb и перенос:

   ```bash
   ssh cs13661@vh426.timeweb.ru 'mysqldump --single-transaction --routines --no-tablespaces \
     --default-character-set=utf8mb4 -u cs13661_egormath -p"$(cat ~/egormath/.secrets/DB_PASSWORD)" \
     cs13661_egormath | gzip' > /tmp/egormath.sql.gz
   scp /tmp/egormath.sql.gz chemolymp-demo:/opt/egormath/data/backups/timeweb.sql.gz
   ```
3. Файлы — через Mac (у сервера нет ключа к Timeweb):

   ```bash
   # на Mac
   T=cs13661@vh426.timeweb.ru:/home/c/cs13661/egormath
   mkdir -p /tmp/egormath-move/{media,var,live}
   rsync -az "$T/media/" /tmp/egormath-move/media/
   rsync -az "$T/var/" /tmp/egormath-move/var/
   rsync -az --include='*.txt' --exclude='*' "$T/public_html/live/" /tmp/egormath-move/live/
   for d in media var live; do
     rsync -az /tmp/egormath-move/$d/ chemolymp-demo:/opt/egormath/data/$d/
   done
   ```

   При переключении — те же команды с `--delete`: переедет только разница.
4. `deploy/vps/import-db.sh data/backups/timeweb.sql.gz`, затем `deploy.sh`.
   Записать время заливки — это окно простоя при переключении.
5. Пройти чеклист в браузере на `https://vps.math.emukhin.ru`: вход (старая сессия
   жива), база задач, конструктор, PDF листка и презентации (новая сборка), Gemini,
   фото решения 10–15 МБ, живые страницы в двух браузерах (в простое только
   `live/…txt`, фрагменты — 304 или после изменений), xlsx, админка;
   chemolymp открывается.

### Переключение (окно без уроков, 10–20 мин)

1. За сутки: TTL A-записи `math` → 300 с.
2. Один коммит `main` на обоих серверах.
3. Timeweb → 503: в начало `public_html/.htaccess` —
   `RewriteEngine On` / `RewriteRule ^ - [R=503,L]` (+ `ErrorDocument 503` со
   страницей «Сайт переезжает»). С этого момента база Timeweb не меняется.
4. Финальный дамп (как в репетиции) → `import-db.sh … --yes`; файлы — командами
   из п. 3 репетиции с `--delete`.
5. Сверить числа строк (печатает `import-db.sh`) с Timeweb:
   `SELECT COUNT(*)` по `auth_user`, `django_session`, выдачам, попыткам, доскам.
6. DNS: A `math` → `77.232.132.139`. `.env`:
   `EGORMATH_HOSTS=math.emukhin.ru, vps.math.emukhin.ru` → `deploy.sh`
   (Caddy выпустит сертификат за секунды). Имя `math.emukhin.ru` добавлять только
   сейчас: раньше Caddy безуспешно запрашивал бы сертификат и упёрся бы в лимит
   Let's Encrypt на неудачные проверки.
7. Следить: `docker compose … logs -f egormath-web` и логи Caddy chemolymp.

### Откат (2 недели после переезда Timeweb не трогаем)

- В окне переключения: A-запись обратно на Timeweb, убрать 503 из `.htaccess`.
- Позже: остановить приём данных на VPS (`docker compose … stop egormath-web`),
  `backup.sh` → залить дамп в MySQL Timeweb, rsync media/var/live обратно,
  убрать 503 на Timeweb, DNS на Timeweb.
  Миграции в эти 2 недели — только совместимые с обоими серверами.

### После переезда

- Убрать задание очистки из планировщика Timeweb, вернуть TTL 3600.
- rclone + `BACKUP_RCLONE_REMOTE` — сделано 27.09; осталось `BACKUP_SECRETS_PASSPHRASE`
  и `BACKUP_PING_URL` (раздел «Бэкапы»).
- Внешний мониторинг `https://math.emukhin.ru/healthz`.
- Удалить CGI-обвязку (`public_html/wsgi.py`, `.htaccess`, `deploy/deploy.sh`) и
  обновить `CLAUDE.md`/`AGENTS.md` — отдельным PR после отказа от отката.
