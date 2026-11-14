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
| `mathlive/` | mathlive.min.js, sounds/*.wav (5 звуков клавиатуры) | 0.110.0 | https://cdn.jsdelivr.net/npm/mathlive@0.110.0/ | MIT (`mathlive/LICENSE`) |
| `modern-screenshot/` | modern-screenshot.js (= dist/index.js) | 4.6.8 | https://cdn.jsdelivr.net/npm/modern-screenshot@4.6.8/dist/index.js | MIT (`modern-screenshot/LICENSE`) |

В `katex.min.css` оставлены только `woff2` (woff и ttf вырезаны: их
понимают все браузеры с 2018 года, а файлов втрое меньше). Подмножества
greek, greek-ext и vietnamese Inter не нужны: латиница и кириллица.

MathLive (редактор формул в масках и ответе ученика) без своих шрифтов:
его `fonts/` — те же 20 файлов KaTeX байт в байт, а `katex.min.css` стоит в
`base.html` на каждой странице, поэтому `input.css` ставит
`--ML__static-fonts: true`, и MathLive берёт готовые `@font-face` KaTeX_*
(иначе он грузил бы копии по пути `./fonts/` от адреса скрипта, мимо имён
с хэшем манифеста). Звуки он сам берёт из `./sounds/` относительно адреса
скрипта — на проде это `/static/vendor/mathlive/sounds/*.wav` без хэша:
`collectstatic` оставляет и исходные имена, Caddy кэширует их на неделю.
Локали, sourcemap, `mathlive-static.css`, `mathlive-fonts.css` и
ESM-сборки не нужны. modern-screenshot (кнопка «Картинкой», `task_png.js`)
грузится лениво по нажатию; его адрес с хэшем `base.html` передаёт в
`data-lib` тега скрипта.

Обновление: скачать новую версию по тем же адресам, сверить хэши с
unpkg.com, заменить файлы и номер версии здесь; на проде имена с хэшем
содержимого подхватит `collectstatic` (core/staticfiles.py).
