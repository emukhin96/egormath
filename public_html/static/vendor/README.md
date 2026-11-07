# Сторонние библиотеки и шрифты (самохостинг)

Раньше грузились с cdn.jsdelivr.net и fonts.googleapis.com: два блокирующих
рендер CSS с чужих доменов и 3–7 запросов на чужие хосты на каждой
странице, плюс зависимость от доступности этих CDN из школьных сетей
(аудит быстродействия 06.11.2026, docs/PERF_AUDIT_2026-11.md, пункт 5).

| Каталог | Что | Версия | Откуда | Лицензия |
|---------|-----|--------|--------|----------|
| `katex/` | katex.min.css, katex.min.js, contrib/auto-render.min.js, fonts/*.woff2 | 0.16.11 | https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/ | MIT (`katex/LICENSE`) |
| `inter/` | inter.css + 4 подмножества woff2 (cyrillic, cyrillic-ext, latin, latin-ext), переменный вес 400–700 | Google Fonts v20 | https://fonts.googleapis.com/css2?family=Inter:wght@400..700 (файлы с fonts.gstatic.com) | OFL 1.1 (`inter/LICENSE.txt`) |
| `sortable/` | Sortable.min.js | 1.15.6 | https://cdn.jsdelivr.net/npm/sortablejs@1.15.6/ | MIT (`sortable/LICENSE`) |

В `katex.min.css` оставлены только `woff2` (woff и ttf вырезаны: их
понимают все браузеры с 2018 года, а файлов втрое меньше). Подмножества
greek, greek-ext и vietnamese Inter не нужны: латиница и кириллица.

MathLive (редактор формул в масках) по-прежнему с cdn.jsdelivr.net —
он сам подгружает свои шрифты и звуки относительно адреса скрипта; перенос
отдельной задачей.

Обновление: скачать новую версию по тем же адресам, сверить хэши с
unpkg.com, заменить файлы и номер версии здесь; на проде имена с хэшем
содержимого подхватит `collectstatic` (core/staticfiles.py).
