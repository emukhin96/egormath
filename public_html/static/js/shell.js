document.addEventListener("DOMContentLoaded", () => {
  // После входа в другой вкладке Django меняет CSRF-cookie, а старая форма
  // остаётся в DOM. Перед выходом берём актуальный токен той же сессии.
  const logout = document.querySelector("form[data-logout]");
  if (logout) {
    logout.addEventListener("submit", () => {
      const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
      const field = logout.querySelector('[name="csrfmiddlewaretoken"]');
      if (token && field) field.value = decodeURIComponent(token[1]);
    });
  }

  // Выпадающие подразделы главного меню: шеврон открывает список, клик
  // вне меню, Escape или второй клик закрывают. На узком экране кнопка
  // скрыта CSS, а ссылки стоят в общем ряду.
  const navButtons = Array.from(document.querySelectorAll("[data-nav-more]"));
  const closeNavMenus = (except) => {
    navButtons.forEach((button) => {
      if (button === except) return;
      button.setAttribute("aria-expanded", "false");
      const menu = button.nextElementSibling;
      if (menu) menu.classList.remove("is-open");
    });
  };
  navButtons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = button.nextElementSibling;
      if (!menu) return;
      const open = !menu.classList.contains("is-open");
      closeNavMenus(button);
      menu.classList.toggle("is-open", open);
      button.setAttribute("aria-expanded", String(open));
    });
  });
  if (navButtons.length) {
    document.addEventListener("click", () => closeNavMenus());
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeNavMenus();
    });
  }

  // Фильтры без кнопки «Применить»: select, радио и галочки с data-autosubmit
  // (или внутри формы с data-autosubmit) отправляют форму при изменении.
  // Текстовые поля отправляются по Enter (штатно). Поля даты/числа дают
  // change на каждом промежуточном вводе с клавиатуры («0002-05-10»),
  // поэтому их отправляем при уходе с поля, если значение изменилось и
  // полное; Enter в них отправляет форму штатно.
  // requestSubmit, чтобы сработали submit-обработчики (живой поиск finder).
  const AUTOSUBMIT_SCOPE = "[data-autosubmit], [data-autosubmit] *";
  const TYPED_FIELDS = 'input[type="date"], input[type="datetime-local"], input[type="month"], input[type="week"], input[type="time"], input[type="number"]';
  const submitFilters = (form) => {
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  };
  const autosubmitField = (target) => (
    target instanceof HTMLElement && target.form
    && target.matches(AUTOSUBMIT_SCOPE) ? target : null);
  const typedValueComplete = (field) => {
    if (!field.value) return true;
    if (!field.checkValidity()) return false;
    // Год из четырёх цифр не раньше 1900: недописанный год не отправляем
    const year = field.value.match(/^(\d{4,})-/);
    return !year || Number(year[1]) >= 1900;
  };
  document.addEventListener("focusin", (event) => {
    const field = autosubmitField(event.target);
    if (field && field.matches(TYPED_FIELDS)) field.dataset.autosubmitInitial = field.value;
  });
  document.addEventListener("focusout", (event) => {
    const field = autosubmitField(event.target);
    if (!field || !field.matches(TYPED_FIELDS)) return;
    const initial = field.dataset.autosubmitInitial;
    delete field.dataset.autosubmitInitial;
    if (initial === undefined || initial === field.value) return;
    if (typedValueComplete(field)) submitFilters(field.form);
  });
  // В форме без кнопки отправки и с несколькими такими полями браузер
  // не отправляет форму по Enter сам — делаем это явно.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const field = autosubmitField(event.target);
    if (!field || !field.matches(TYPED_FIELDS)) return;
    event.preventDefault();
    if (!typedValueComplete(field)) return;
    delete field.dataset.autosubmitInitial;
    submitFilters(field.form);
  });
  document.addEventListener("change", (event) => {
    const field = autosubmitField(event.target);
    if (!field) return;
    if (field.matches('input[type="text"], input[type="search"], textarea')) return;
    if (field.matches(TYPED_FIELDS)) return;
    submitFilters(field.form);
  });

  const sidebar = document.getElementById("context-sidebar");
  const toggle = document.getElementById("context-toggle");
  const close = document.getElementById("sidebar-close");
  const backdrop = document.getElementById("sidebar-backdrop");

  if (!sidebar || !toggle || !close || !backdrop) {
    return;
  }

  const setOpen = (open) => {
    sidebar.classList.toggle("is-open", open);
    backdrop.classList.toggle("is-visible", open);
    toggle.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("sidebar-open", open);
    if (open) {
      close.focus();
    } else {
      toggle.focus();
    }
  };

  toggle.addEventListener("click", () => {
    setOpen(!sidebar.classList.contains("is-open"));
  });
  close.addEventListener("click", () => setOpen(false));
  backdrop.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
      setOpen(false);
    }
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 760 && sidebar.classList.contains("is-open")) {
      sidebar.classList.remove("is-open");
      backdrop.classList.remove("is-visible");
      toggle.setAttribute("aria-expanded", "false");
      document.body.classList.remove("sidebar-open");
    }
  });
});
