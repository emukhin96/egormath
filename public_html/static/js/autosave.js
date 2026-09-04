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
    badge.textContent = message || (ok ? 'Сохранено ✓' : 'Ошибка сохранения');
    badge.classList.toggle('ws-saved-error', !ok);
    badge.hidden = false;
    clearTimeout(badgeTimer);
    badgeTimer = setTimeout(function () { badge.hidden = true; }, ok ? 1500 : 4000);
  }

  /* keepalive: запрос доживает до ответа, даже если страница уже уходит
     (нажали submit другой кнопкой, закрыли вкладку) — иначе последнее
     изменение поля пропадает. Лимит тела для keepalive — 64 КБ. */
  function send(form, body) {
    return fetch(form.action, {
      method: 'POST',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      body: body,
      keepalive: true,
    }).then(function (r) {
      return r.json().catch(function () { return {ok: r.ok, message: ''}; });
    }).then(function (data) {
      showSaved(data.ok, data.message);
      /* Страница может дорисовать что-то по ответу сервера (например,
         результат сверки) — отдаём ей данные событием на форме */
      form.dispatchEvent(new CustomEvent('autosave:done', {detail: data, bubbles: true}));
    }).catch(function () {
      showSaved(false, 'Нет связи — изменение не сохранено');
    });
  }

  /* Запросы одной формы выполняются строго по очереди: параллельные fetch
     могут завершиться не по порядку, и сервер записал бы устаревшее
     значение. Данные снимаются в момент вызова, до постановки в очередь. */
  var queues = new WeakMap();

  function autosave(form) {
    var body = new FormData(form);
    var queued = (queues.get(form) || Promise.resolve()).then(function () {
      return send(form, body);
    });
    queues.set(form, queued);
  }

  var debounceTimers = new WeakMap();
  function autosaveDebounced(form) {
    clearTimeout(debounceTimers.get(form));
    debounceTimers.set(form, setTimeout(function () { autosave(form); }, 800));
  }

  document.addEventListener('change', function (e) {
    var control = e.target;
    var form = (control.closest && control.closest('form'))
      || control.form
      || (control.getAttribute && control.getAttribute('form')
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

  /* Flash-сообщения Django (success/info) — тот же тост справа снизу. */
  document.addEventListener('DOMContentLoaded', function () {
    var nodes = document.querySelectorAll('.ws-toast-src');
    if (!nodes.length) return;
    var i = 0;
    function next() {
      if (i >= nodes.length) return;
      var node = nodes[i++];
      showSaved(node.dataset.ok !== '0', (node.textContent || '').trim());
      node.hidden = true;
      if (i < nodes.length) {
        setTimeout(next, node.dataset.ok !== '0' ? 1600 : 4100);
      }
    }
    next();
  });
})();
