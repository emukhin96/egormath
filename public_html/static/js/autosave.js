/* Общее автосохранение форм через fetch с индикатором «Сохранено».
   Форма помечается data-autosave="change" (сохранение при изменении поля,
   в т.ч. полей, привязанных атрибутом form=…) или data-autosave="debounce"
   (текстовый ввод с задержкой; Enter/submit сохраняет сразу). */
(function () {
  'use strict';

  var badgeTimer = null;

  /* action — необязательная кнопка в тосте: {label: 'Отменить', onClick}.
     С кнопкой тост держится дольше и не исчезает, пока над ним курсор. */
  function showSaved(ok, message, action) {
    var badge = document.getElementById('ws-saved');
    if (!badge) return;
    badge.textContent = message || (ok ? 'Сохранено ✓' : 'Ошибка сохранения');
    badge.classList.toggle('ws-saved-error', !ok);
    var delay = ok ? 1500 : 4000;
    if (action && action.label) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'ws-saved-action';
      button.textContent = action.label;
      button.addEventListener('click', function () {
        clearTimeout(badgeTimer);
        badge.hidden = true;
        action.onClick();
      });
      badge.appendChild(document.createTextNode(' · '));
      badge.appendChild(button);
      delay = 8000;
    }
    badge.hidden = false;
    clearTimeout(badgeTimer);
    function hide() { badge.hidden = true; }
    badgeTimer = setTimeout(hide, delay);
    badge.onmouseenter = action ? function () { clearTimeout(badgeTimer); } : null;
    badge.onmouseleave = action ? function () { badgeTimer = setTimeout(hide, 3000); } : null;
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
      return !!data.ok;
    }).catch(function () {
      showSaved(false, 'Нет связи — изменение не сохранено');
      return false;
    });
  }

  /* Запросы одной формы выполняются строго по очереди: параллельные fetch
     могут завершиться не по порядку, и сервер записал бы устаревшее
     значение. Данные снимаются в момент вызова, до постановки в очередь. */
  var queues = new WeakMap();

  function enqueue(form, operation) {
    var queued = (queues.get(form) || Promise.resolve()).catch(function () {}).then(operation);
    queues.set(form, queued);
    return queued;
  }

  function autosave(form) {
    var body = new FormData(form);
    return enqueue(form, function () { return send(form, body); });
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

  function initDebouncedForms() {
    document.querySelectorAll('form[data-autosave=debounce]:not([data-autosave-ready])').forEach(function (form) {
      form.dataset.autosaveReady = '1';
      form.addEventListener('input', function () { autosaveDebounced(form); });
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        clearTimeout(debounceTimers.get(form));
        autosave(form);
      });
    });
  }
  document.addEventListener('DOMContentLoaded', initDebouncedForms);
  document.addEventListener('worksheet:updated', initDebouncedForms);

  window.EgorAutosave = {showSaved: showSaved, autosave: autosave, enqueue: enqueue};

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
