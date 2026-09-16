/* Представления рабочего места; сохранение выполняют обычные серверные формы. */
(function () {
  document.addEventListener('submit', async function (event) {
    var parts = event.target.closest('[data-iw-parts]');
    if (!parts || (event.submitter && event.submitter.hasAttribute('formaction'))) return;
    event.preventDefault();
    if (parts.dataset.busy) return;
    parts.dataset.busy = '1';
    var button = event.submitter;
    if (button) button.disabled = true;
    try {
      var response = await fetch(location.href, {method: 'POST', body: new FormData(parts), headers: {'X-Requested-With': 'XMLHttpRequest'}});
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Не удалось сохранить подпункты');
      if (window.EgorAutosave) EgorAutosave.showSaved(true, result.message);
    } catch (error) {
      if (window.EgorAutosave) EgorAutosave.showSaved(false, error.message);
    } finally { delete parts.dataset.busy; if (button) button.disabled = false; }
  });
  var form = document.querySelector('[data-iw-source]');
  if (form) {
    function source() {
      var selected = form.querySelector('[name=source_mode]:checked').value;
      form.querySelectorAll('[data-iw-source-fields]').forEach(function (panel) {
        panel.hidden = panel.dataset.iwSourceFields !== selected;
        panel.querySelectorAll('select').forEach(function (input) { input.disabled = panel.hidden; });
      });
    }
    form.addEventListener('change', source); source();
  }
  document.querySelectorAll('[data-iw-tab]').forEach(function (button) {
    button.addEventListener('click', function () {
      var tab = button.dataset.iwTab;
      document.querySelectorAll('[data-iw-panel]').forEach(function (panel) { panel.hidden = panel.dataset.iwPanel !== tab; });
      document.querySelectorAll('[data-iw-tab]').forEach(function (item) { item.setAttribute('aria-pressed', String(item === button)); });
      var url = new URL(location.href); url.searchParams.set('tab', tab); history.replaceState(null, '', url);
      document.querySelectorAll('[data-iw-panel="catalog"] a[href]').forEach(function (link) {
        var target = new URL(link.href, location.href);
        if (target.pathname === location.pathname) { target.searchParams.set('tab', 'catalog'); link.href = target; }
      });
    });
  });
})();
