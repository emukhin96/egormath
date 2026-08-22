---
name: Workbench production redesign
overview: Перенести визуальную систему варианта «Рабочая панель» в production через существующий Tailwind v4 pipeline. Основные разделы останутся горизонтально в шапке, а боковая панель станет контекстной для каждого авторизованного экрана и на мобильных будет открываться поверх содержимого.
todos:
  - id: shell-foundation
    content: Перенести workbench-токены в Tailwind и собрать общую оболочку с горизонтальной top-nav и контекстным sidebar
    status: completed
  - id: sidebar-context
    content: Создать контекстные sidebar-partials и подготовить необходимые данные во views без N+1
    status: completed
  - id: primary-screens
    content: Перерисовать dashboard учителя/ученика, базу задач, конструктор и список учеников
    status: completed
  - id: secondary-screens
    content: Унифицировать остальные авторизованные detail/form/import/review экраны и минимальную оболочку guest/public
    status: completed
  - id: responsive-safety
    content: Добавить responsive/off-canvas поведение, сохранив JS-контракты builder/autosave/KaTeX
    status: completed
  - id: redesign-verification
    content: Пересобрать CSS, прогнать тесты и вручную проверить ключевые сценарии и размеры экранов
    status: completed
isProject: false
---

# Внедрение «Рабочей панели»

## Архитектура оболочки
- Перестроить [`public_html/templates/base.html`](public_html/templates/base.html) в app-shell: белая шапка с брендом, горизонтальными ссылками «Главная / База задач / Листки / Ученики», профилем и выходом; ниже — контекстный sidebar и широкая рабочая область.
- Добавить в `base.html` блоки `sidebar`, `page_actions` и `extra_js`. Основная навигация остаётся только в шапке; sidebar не содержит повторяющихся ссылок на разделы.
- Login и публичный листок оставить в минимальной оболочке без sidebar. Для авторизованных страниц без специального контекста использовать компактную справочную панель.
- На мобильных верхняя навигация остаётся одной горизонтальной разметкой с прокруткой, а контекстный sidebar открывается кнопкой «Контекст». Реализовать доступное открытие/закрытие, Escape и `aria-expanded` в новом [`public_html/static/js/shell.js`](public_html/static/js/shell.js).

## Tailwind и визуальная система
- Перенести только production-часть первого прототипа из [`docs/design-demos/demo.css`](docs/design-demos/demo.css) в [`public_html/static/css/input.css`](public_html/static/css/input.css): navy `#102b55`, accent `#1765b5`, светлый фон, радиус 7px, плотные панели, app-shell, горизонтальный topbar, sidebar, компактные таблицы и responsive rules.
- Сохранить текущую архитектуру Tailwind v4: токены в `@theme`/`:root`, semantic-классы в `@layer components`, сборка `input.css → app.css`. Не подключать `demo.css` и не переносить SPA-логику `demo.js`.
- Не переименовывать существующие контракты `.btn`, `.card`, `.list`, `.badge-*`, `.math-content`, `.ws-*`, `#ws-items`, `#ws-saved` и `form[data-autosave]`; изменить их оформление совместимо с рабочей панелью.

## Контекстная боковая панель
- Создать переиспользуемые partials в [`public_html/templates/includes/sidebar/`](public_html/templates/includes/sidebar/) и подключать их через `{% block sidebar %}`:
  - учительский dashboard — очередь проверки, ближайшие действия и последние листки;
  - ученический dashboard и задание — срок, статус и прогресс;
  - база задач — рубрикатор, активные фильтры и число результатов;
  - карточка/форма задачи — метаданные, темы и подсказки LaTeX/изображений;
  - список и конструктор листков — фильтры, метаданные, назначения, публикация и pending review;
  - ученики — активная группа и сводка;
  - проверка работы — ученик, статус, шкала оценки и действия;
  - импорт, bulk answers, tex/error — формат, статистика или диагностические подсказки.
- Добавить только необходимые дешёвые агрегаты и уже предзагруженные данные в [`public_html/accounts/views.py`](public_html/accounts/views.py), [`public_html/problems/views.py`](public_html/problems/views.py), [`public_html/worksheets/views.py`](public_html/worksheets/views.py) и [`public_html/assignments/views.py`](public_html/assignments/views.py), избегая N+1.

## Перерисовка экранов
- Перевести все 17 авторизованных full-page шаблонов в плотную рабочую композицию: единый `page-head`, panel/card, компактные фильтры, полноширинные таблицы и согласованные действия.
- В первую очередь приблизить к прототипу [`public_html/templates/accounts/dashboard_teacher.html`](public_html/templates/accounts/dashboard_teacher.html), [`public_html/templates/accounts/dashboard_student.html`](public_html/templates/accounts/dashboard_student.html), [`public_html/templates/problems/task_list.html`](public_html/templates/problems/task_list.html), [`public_html/templates/worksheets/worksheet_detail.html`](public_html/templates/worksheets/worksheet_detail.html) и [`public_html/templates/accounts/students.html`](public_html/templates/accounts/students.html).
- Затем унифицировать detail/form/import/review страницы. В конструкторе менять только композицию и стили, сохранив DOM-контракты Sortable, звёзд, answer toggle, CSRF и autosave.
- Реальные Django URL и формы остаются источником действий; не добавлять фиктивный глобальный поиск, activity timeline или статистику, которых нет в backend.

## Адаптивность и проверка
- Для широких экранов использовать рабочую область до 1460px; при 1050px перестраивать сетки, при 760px переводить sidebar в off-canvas, фильтры — в колонку, таблицы — во внутренний горизонтальный scroll.
- Пересобрать [`public_html/static/css/app.css`](public_html/static/css/app.css), прогнать Django tests и проверку свежести CSS.
- Вручную проверить роли учителя и ученика: login/logout, все основные и вторичные страницы, фильтры и inline autosave базы задач, drag-and-drop/звёзды/ответы/автосохранение конструктора, назначение и проверку работы, KaTeX, публичный листок, desktop/tablet/mobile.
- Снять контрольные скриншоты ключевых экранов и обновить [`docs/PIPELINE.md`](docs/PIPELINE.md) только если появятся новые правила shell/sidebar.
