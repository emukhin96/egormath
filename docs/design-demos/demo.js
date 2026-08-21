const variants = {
  workbench: {
    name: "Рабочая панель",
    eyebrow: "Плотный интерфейс",
    description: "Максимум информации и быстрых действий на одном экране.",
  },
  academy: {
    name: "Современная академия",
    eyebrow: "Рекомендуемый вариант",
    description: "Спокойная образовательная среда с ясной иерархией.",
  },
  documents: {
    name: "Документы и математика",
    eyebrow: "Фокус на содержании",
    description: "Рабочая область напоминает редактор учебных материалов.",
  },
  cards: {
    name: "Модульные карточки",
    eyebrow: "Дружелюбный интерфейс",
    description: "Наглядные статусы и крупные точки входа в основные действия.",
  },
};

const icons = {
  home: '<svg viewBox="0 0 24 24"><path d="m3 10 9-7 9 7v10h-6v-6H9v6H3z"/></svg>',
  tasks: '<svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/></svg>',
  sheets: '<svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v15H6zM14 3v4h4M9 11h6M9 15h6"/></svg>',
  users: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v1"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  menu: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></svg>',
  arrow: '<svg viewBox="0 0 24 24"><path d="M5 12h14M14 7l5 5-5 5"/></svg>',
};

const tasks = [
  ["Квадратные уравнения", "8", "Алгебра", "2; 3", "1"],
  ["Площадь четырёхугольника ABCD", "8", "Геометрия", "24", "2"],
  ["Параметр в уравнении", "9", "Алгебра", "a = ±6", "3"],
  ["Комбинаторная раскраска", "10", "Олимпиадные", "12", "4"],
  ["Последовательности и прогрессии", "9", "Алгебра", "128", "5"],
];

function navButton(screen, label, icon) {
  return `<button class="nav-link" data-screen="${screen}">
    <span class="nav-icon">${icons[icon]}</span><span>${label}</span>
  </button>`;
}

function shell() {
  const theme = document.body.dataset.theme;
  const variant = variants[theme];
  document.title = `${variant.name} — EgorMath demo`;
  document.body.innerHTML = `
    <div class="demo-bar">
      <a href="index.html" class="demo-back">← Все варианты</a>
      <div class="demo-variant">
        <span>${variant.eyebrow}</span>
        <strong>${variant.name}</strong>
      </div>
      <div class="viewport-switch" aria-label="Размер макета">
        <button data-width="desktop" class="is-active">Десктоп</button>
        <button data-width="tablet">Планшет</button>
        <button data-width="mobile">Телефон</button>
      </div>
    </div>
    <div class="preview-frame" id="preview-frame">
      <div class="app-shell">
        <header class="topbar">
          <button class="icon-button menu-button" id="menu-button" aria-label="Открыть меню">${icons.menu}</button>
          <button class="brand" data-screen="teacher">Egor<span>Math</span></button>
          <div class="topbar-search"><span>${icons.search}</span><input placeholder="Поиск по задачам и листкам"></div>
          <div class="profile"><div class="avatar">Е</div><div><strong>Егор Мухин</strong><span>Учитель</span></div></div>
        </header>
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-label">Рабочее пространство</div>
          ${navButton("teacher", "Главная", "home")}
          ${navButton("tasks", "База задач", "tasks")}
          ${navButton("builder", "Листки", "sheets")}
          ${navButton("students", "Ученики", "users")}
          <div class="sidebar-label student-label">Режим ученика</div>
          ${navButton("student", "Мои задания", "check")}
          <div class="sidebar-note"><span>Демо</span><p>${variant.description}</p></div>
        </aside>
        <main class="content" id="content"></main>
      </div>
    </div>
    <div class="toast" id="toast">Изменения сохранены</div>
  `;
}

function teacherScreen() {
  return `
    <div class="page-head">
      <div><span class="eyebrow">22 августа, суббота</span><h1>Добро пожаловать, Егор</h1>
      <p>Здесь собраны задачи, требующие вашего внимания.</p></div>
      <button class="button primary" data-action="create">${icons.plus} Создать листок</button>
    </div>
    <section class="stats">
      <article class="stat-card accent"><span>На проверке</span><strong>4</strong><small>+2 за сегодня</small></article>
      <article class="stat-card"><span>Активных листков</span><strong>9</strong><small>3 с дедлайном</small></article>
      <article class="stat-card"><span>Учеников</span><strong>12</strong><small>2 группы</small></article>
      <article class="stat-card"><span>Выполнено</span><strong>78%</strong><small>за эту неделю</small></article>
    </section>
    <div class="dashboard-grid">
      <section class="panel review-panel">
        <div class="panel-head"><div><span class="eyebrow">Приоритет</span><h2>Ожидают проверки</h2></div>
          <button class="text-button">Посмотреть все ${icons.arrow}</button></div>
        <div class="review-list">
          ${reviewRow("Анна Смирнова", "Квадратные уравнения", "12 мин назад", "АС", "urgent")}
          ${reviewRow("Василий Пупкин", "Вступительное испытание", "1 час назад", "ВП", "")}
          ${reviewRow("Мария Орлова", "Геометрия: площади", "вчера, 19:42", "МО", "")}
          ${reviewRow("Илья Волков", "Комбинаторика", "вчера, 18:15", "ИВ", "")}
        </div>
      </section>
      <section class="panel activity-panel">
        <div class="panel-head"><div><span class="eyebrow">Недавнее</span><h2>Активность</h2></div></div>
        <div class="timeline">
          <div><i></i><p><strong>Проверена работа</strong><span>Василий Пупкин · 09:32</span></p></div>
          <div><i></i><p><strong>Назначен листок</strong><span>Группа 8А · вчера</span></p></div>
          <div><i></i><p><strong>Добавлено 5 задач</strong><span>Алгебра · вчера</span></p></div>
        </div>
      </section>
    </div>
    <section class="panel sheets-panel">
      <div class="panel-head"><div><span class="eyebrow">Материалы</span><h2>Мои листки</h2></div>
        <button class="secondary button" data-screen="builder">Открыть конструктор</button></div>
      <div class="sheet-grid">
        ${sheetCard("Вступительное испытание", "9 класс", "15 задач", "Опубликован")}
        ${sheetCard("Квадратные уравнения", "8 класс", "12 задач", "Черновик")}
        ${sheetCard("Геометрия: площади", "8 класс", "9 задач", "Опубликован")}
      </div>
    </section>`;
}

function reviewRow(name, sheet, time, initials, kind) {
  return `<button class="review-row ${kind}" data-action="review">
    <span class="avatar small">${initials}</span><span class="review-person"><strong>${name}</strong><small>${sheet}</small></span>
    <span class="review-time">${icons.clock}${time}</span><span class="row-arrow">${icons.arrow}</span>
  </button>`;
}

function sheetCard(title, grade, count, status) {
  const statusClass = status === "Черновик" ? "draft" : "published";
  return `<article class="sheet-card"><div class="sheet-icon">${icons.sheets}</div>
    <span class="badge ${statusClass}">${status}</span><h3>${title}</h3>
    <p>${grade} · ${count}</p><div class="sheet-actions"><button>Открыть</button><button>PDF</button></div></article>`;
}

function studentScreen() {
  return `
    <div class="page-head student-head"><div><span class="eyebrow">Кабинет ученика</span><h1>Мои задания</h1>
      <p>Одно задание требует внимания на этой неделе.</p></div>
      <div class="progress-ring"><strong>78%</strong><span>за неделю</span></div></div>
    <section class="focus-card">
      <div class="focus-copy"><span class="badge due">До 25 августа</span><span class="eyebrow">Текущее задание</span>
      <h2>Квадратные уравнения</h2><p>Егор Мухин · 8 класс · 12 задач</p>
      <div class="focus-progress"><span><i style="width: 58%"></i></span><small>Выполнено 7 из 12</small></div></div>
      <button class="button primary" data-action="open">Продолжить ${icons.arrow}</button>
    </section>
    <div class="section-title"><div><span class="eyebrow">Дальше</span><h2>Остальные задания</h2></div>
      <div class="segmented"><button class="is-active">Активные</button><button>Завершённые</button></div></div>
    <div class="assignment-grid">
      ${assignmentCard("Геометрия: площади", "28 августа", "9 задач", "Новая работа", 0)}
      ${assignmentCard("Проценты и пропорции", "30 августа", "15 задач", "В работе", 40)}
      ${assignmentCard("Комбинаторика", "Без срока", "8 задач", "Возвращено", 72)}
    </div>`;
}

function assignmentCard(title, date, count, status, progress) {
  return `<article class="assignment-card"><div class="assignment-top"><span class="badge">${status}</span><span>${date}</span></div>
    <div class="subject-mark">∑</div><h3>${title}</h3><p>${count} · Егор Мухин</p>
    <div class="mini-progress"><i style="width:${progress}%"></i></div>
    <button class="text-button" data-action="open">${progress ? "Продолжить" : "Начать"} ${icons.arrow}</button></article>`;
}

function tasksScreen() {
  return `
    <div class="page-head"><div><span class="eyebrow">Материалы</span><h1>База задач</h1>
      <p>Быстрый поиск и редактирование математических задач.</p></div>
      <button class="button primary" data-action="create">${icons.plus} Новая задача</button></div>
    <section class="filter-panel">
      <label class="search-field">${icons.search}<input id="task-search" placeholder="Введите условие или тему"></label>
      <select><option>Все классы</option><option>8 класс</option><option>9 класс</option></select>
      <select><option>Все темы</option><option>Алгебра</option><option>Геометрия</option></select>
      <button class="secondary button" id="reset-search">Сбросить</button>
    </section>
    <div class="topic-chips"><button class="is-active">Все</button><button>Алгебра</button><button>Геометрия</button>
      <button>Олимпиадные</button><button>Комбинаторика</button></div>
    <section class="panel table-panel">
      <div class="table-meta"><strong>Найдено 248 задач</strong><span>Изменения сохраняются автоматически</span></div>
      <div class="task-table" id="task-table">
        <div class="task-tr task-th"><span>Задача</span><span>Класс</span><span>Тема</span><span>Ответ</span><span></span></div>
        ${tasks.map(taskRow).join("")}
      </div>
    </section>`;
}

function taskRow(task) {
  return `<div class="task-tr" data-title="${task[0].toLowerCase()}"><span class="task-name"><i>${task[4]}</i><strong>${task[0]}</strong>
    <small>Найдите значение выражения и запишите полный ответ.</small></span><span>${task[1]}</span>
    <span><b class="topic">${task[2]}</b></span><span class="math">${task[3]}</span>
    <button class="row-action" data-action="edit">Открыть ${icons.arrow}</button></div>`;
}

function builderScreen() {
  return `
    <div class="page-head builder-head"><div><span class="eyebrow">Конструктор листка</span><h1>Вступительное испытание</h1>
      <p>9 класс · 2026/27 учебный год</p></div><div class="head-actions">
      <button class="secondary button" data-action="preview">Предпросмотр</button>
      <button class="button primary" data-action="pdf">Скачать PDF</button></div></div>
    <div class="builder-layout">
      <aside class="builder-tools panel"><span class="eyebrow">Добавить</span>
        <button data-action="add">${icons.plus}<span><strong>Задачу</strong><small>Из базы задач</small></span></button>
        <button data-action="add">${icons.plus}<span><strong>Текст</strong><small>Комментарий или теория</small></span></button>
        <button data-action="add">${icons.plus}<span><strong>Рубрику</strong><small>Раздел листка</small></span></button>
        <hr><label class="toggle"><input type="checkbox" id="answer-toggle"><span></span>Показывать ответы</label>
      </aside>
      <section class="document">
        <div class="paper-head"><span>EGORMATH</span><div><strong>Вступительное испытание</strong><small>9 класс · 2026/27</small></div></div>
        <div class="rubric-title">Краткий ответ</div>
        ${builderTask(1, "Найдите значение выражения: 16a² − 24ab + 9b² − 4a + 3b.", "4")}
        ${builderTask(2, "Найдите значение выражения x² + 1/x², если x + 1/x = −6.", "34")}
        ${builderTask(3, "Найдите наименьшее целое число решения неравенства.", "7")}
        <div class="rubric-title">Развёрнутый ответ</div>
        ${builderTask(4, "В сплав магния и алюминия добавили 15 кг магния. Определите первоначальную массу.", "45 кг")}
      </section>
      <aside class="properties panel"><span class="eyebrow">Параметры</span><h3>Оформление</h3>
        <label>Формат<select><option>A4, книжный</option><option>A5, книжный</option></select></label>
        <label>Колонки<select><option>Одна колонка</option><option>Две колонки</option></select></label>
        <label>Шрифт<select><option>CMU Serif</option><option>SchoolBook</option></select></label>
        <button class="secondary button" data-action="save">Сохранить свойства</button>
      </aside>
    </div>`;
}

function builderTask(number, text, answer) {
  return `<article class="document-task" draggable="true"><span class="drag">⋮⋮</span><strong>${number}.</strong>
    <span class="stars" aria-label="Сложность"><button>★</button><button>☆</button><button>☆</button></span>
    <p>${text}</p><span class="demo-answer">Ответ: ${answer}</span><button class="task-menu">•••</button></article>`;
}

function studentsScreen() {
  return `<div class="page-head"><div><span class="eyebrow">Класс</span><h1>Ученики</h1>
    <p>Управление доступом и назначенными заданиями.</p></div>
    <button class="button primary" data-action="create">${icons.plus} Добавить ученика</button></div>
    <section class="stats compact"><article class="stat-card"><span>Всего</span><strong>12</strong></article>
      <article class="stat-card"><span>Активны сегодня</span><strong>8</strong></article>
      <article class="stat-card"><span>Работ на проверке</span><strong>4</strong></article></section>
    <section class="panel student-table">
      ${["Анна Смирнова|АС|8А|92%","Василий Пупкин|ВП|8А|78%","Мария Орлова|МО|9Б|85%","Илья Волков|ИВ|9Б|69%"].map((row) => {
        const [name, initials, group, score] = row.split("|");
        return `<button class="student-row" data-action="student"><span class="avatar small">${initials}</span>
          <span><strong>${name}</strong><small>${group} · вход сегодня</small></span>
          <span class="student-score"><i style="width:${score}"></i></span><b>${score}</b>${icons.arrow}</button>`;
      }).join("")}
    </section>`;
}

const screens = {
  teacher: teacherScreen,
  student: studentScreen,
  tasks: tasksScreen,
  builder: builderScreen,
  students: studentsScreen,
};

function showScreen(name) {
  const renderer = screens[name] || teacherScreen;
  document.querySelector("#content").innerHTML = renderer();
  document.querySelectorAll("[data-screen]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.screen === name);
  });
  document.querySelector("#sidebar").classList.remove("is-open");
  bindScreenInteractions();
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.setTimeout(() => toast.classList.remove("is-visible"), 1800);
}

function bindScreenInteractions() {
  document.querySelectorAll("#content [data-screen]").forEach((button) => {
    button.addEventListener("click", () => showScreen(button.dataset.screen));
  });
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => showToast({
      create: "Форма создания открыта",
      review: "Работа открыта для проверки",
      open: "Задание открыто",
      edit: "Редактор задачи открыт",
      add: "Новый блок добавлен",
      preview: "Предпросмотр сформирован",
      pdf: "PDF поставлен в очередь",
      save: "Свойства сохранены",
      student: "Карточка ученика открыта",
    }[button.dataset.action] || "Готово"));
  });
  const search = document.querySelector("#task-search");
  if (search) {
    search.addEventListener("input", () => {
      const query = search.value.trim().toLowerCase();
      document.querySelectorAll("#task-table .task-tr:not(.task-th)").forEach((row) => {
        row.hidden = !row.dataset.title.includes(query);
      });
    });
    document.querySelector("#reset-search").addEventListener("click", () => {
      search.value = "";
      search.dispatchEvent(new Event("input"));
    });
  }
  const answerToggle = document.querySelector("#answer-toggle");
  if (answerToggle) {
    answerToggle.addEventListener("change", () => {
      document.querySelector(".document").classList.toggle("show-answers", answerToggle.checked);
    });
  }
  document.querySelectorAll(".stars button").forEach((star) => {
    star.addEventListener("click", () => {
      star.textContent = star.textContent === "★" ? "☆" : "★";
      showToast("Сложность изменена");
    });
  });
  document.querySelectorAll(".segmented button, .topic-chips button").forEach((button) => {
    button.addEventListener("click", () => {
      button.parentElement.querySelectorAll("button").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  shell();
  const initialScreen = new URLSearchParams(window.location.search).get("screen");
  showScreen(screens[initialScreen] ? initialScreen : "teacher");
  document.querySelectorAll(".sidebar [data-screen], .brand").forEach((button) => {
    button.addEventListener("click", () => showScreen(button.dataset.screen));
  });
  document.querySelector("#menu-button").addEventListener("click", () => {
    document.querySelector("#sidebar").classList.toggle("is-open");
  });
  document.querySelectorAll("[data-width]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-width]").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      const frame = document.querySelector("#preview-frame");
      frame.className = `preview-frame ${button.dataset.width}`;
    });
  });
});
