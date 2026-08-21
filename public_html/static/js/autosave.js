/* Общее автосохранение форм через fetch с индикатором «Сохранено».
   Форма помечается data-autosave="change" (сохранение при изменении поля,
   в т.ч. полей, привязанных атрибутом form=…) или data-autosave="debounce"
   (текстовый ввод с задержкой; Enter/submit сохраняет сразу). */
(function () {
  'use strict';

  var badgeTimer = null;

  function showSaved(ok, message) {
    var badge = document.getElementById('ws-saved');
    if (!badge) return;
    badge.textContent = ok ? 'Сохранено ✓' : (message || 'Ошибка сохранения');
    badge.classList.toggle('ws-saved-error', !ok);
    badge.hidden = false;
    clearTimeout(badgeTimer);
    badgeTimer = setTimeout(function () { badge.hidden = true; }, ok ? 1500 : 4000);
  }

  function autosave(form) {
    fetch(form.action, {
      method: 'POST',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      body: new FormData(form),
    }).then(function (r) {
      return r.json().catch(function () { return {ok: r.ok, message: ''}; });
    }).then(function (data) {
      showSaved(data.ok, data.message);
    }).catch(function () {
      showSaved(false, 'Нет связи — изменение не сохранено');
    });
  }

  var debounceTimers = new WeakMap();
  function autosaveDebounced(form) {
    clearTimeout(debounceTimers.get(form));
    debounceTimers.set(form, setTimeout(function () { autosave(form); }, 800));
  }

  document.addEventListener('change', function (e) {
    var control = e.target;
    var form = control.form
      || (control.getAttribute('form')
          && document.getElementById(control.getAttribute('form')));
    if (form && form.dataset.autosave === 'change') autosave(form);
  });

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-autosave=debounce]').forEach(function (form) {
      form.addEventListener('input', function () { autosaveDebounced(form); });
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        clearTimeout(debounceTimers.get(form));
        autosave(form);
      });
    });
  });

  window.EgorAutosave = {showSaved: showSaved, autosave: autosave};
})();
