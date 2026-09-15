/* Представления рабочего места; сохранение выполняют обычные серверные формы. */
(function () {
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
