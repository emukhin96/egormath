// Аналоги задачи (ROADMAP 11.2026, п. 2б): список у строки конструктора
// подгружается по клику на «N аналогов» (worksheets.analog_views
// .worksheet_item_analogs) — условия аналогов всех строк сразу не грузим.
// Краткое условие аналога свёрнуто до нескольких строк; клик по нему
// разворачивает целиком. Кнопки строки — обычные формы с перезагрузкой,
// успех — тост #ws-saved из messages (base.html).
(function () {
  function render(root) {
    if (window.renderMathContent) root.querySelectorAll('.math-content').forEach(window.renderMathContent);
  }
  document.addEventListener('click', async function (e) {
    var toggle = e.target.closest('[data-analogs-toggle]');
    if (toggle) {
      var panel = document.getElementById(toggle.getAttribute('aria-controls'));
      if (!panel) return;
      var open = panel.hidden;
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open || panel.dataset.loaded) return;
      panel.dataset.loaded = '1';
      panel.innerHTML = '<p class="helptext">Загружаем аналоги…</p>';
      try {
        var response = await fetch(toggle.dataset.analogsUrl, {credentials: 'same-origin'});
        if (!response.ok) throw new Error();
        panel.innerHTML = await response.text();
        render(panel);
      } catch (error) {
        delete panel.dataset.loaded;
        panel.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
        if (window.EgorAutosave) window.EgorAutosave.showSaved(false, 'Не удалось загрузить аналоги');
      }
      return;
    }
    var body = e.target.closest('.analog-row .analog-body');
    if (body && !e.target.closest('a, button') && !String(window.getSelection())) {
      body.classList.toggle('is-open');
    }
  });
})();
