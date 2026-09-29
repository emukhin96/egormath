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
