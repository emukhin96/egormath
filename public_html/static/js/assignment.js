/* Страница задания ученика.

   1. Подтверждение отправки с числом задач без ответа — по текущему
      состоянию формы (поля и фото), а не по данным на момент загрузки.
   2. Кнопка «Проверить» у задачи: форма уходит fetch'ем на formaction
      кнопки, сервер сохраняет ответы и возвращает результат сверки для
      полей задачи — бейджи обновляются без перезагрузки. Без JS кнопка
      работает как обычный submit с redirect обратно к задаче.
   3. Фото решения: выбор файла сразу отправляет его форму-владельца
      (атрибут form), кнопка «Загрузить» нужна только без JS. */
(function () {
  'use strict';

  function cardAnswered(card) {
    /* math-field не участвует в форме сам — его значение читаем напрямую */
    var controls = card.querySelectorAll('input:not([type=hidden]):not([type=file]), textarea, math-field');
    for (var i = 0; i < controls.length; i++) {
      if ((controls[i].value || '').trim()) return true;
    }
    return !!card.querySelector('[data-photos] img');
  }

  /* Разметка бейджа — как в _check_badge.html */
  var BADGES = {
    ok: ['badge-reviewed', '✓ верно', 'Ответ совпал с эталоном'],
    wrong: ['badge-returned', '✗ неверно', 'Ответ не совпал с эталоном — проверьте запись'],
    unknown: ['badge-assigned', '? не разобрано', 'Автосверка не смогла разобрать ответ; учитель проверит вручную'],
  };

  function renderBadge(holder, status) {
    holder.dataset.status = status || '';
    holder.textContent = '';
    var spec = BADGES[status];
    if (!spec) return;
    var badge = document.createElement('span');
    badge.className = 'badge ' + spec[0];
    badge.textContent = spec[1];
    badge.title = spec[2];
    holder.appendChild(badge);
  }

  function csrf(form) {
    var input = form.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) EgorAutosave.showSaved(ok, message);
  }

  function formSnapshot(form) {
    var parts = [];
    new FormData(form).forEach(function (value, key) {
      if (value && typeof value === 'object' && value.name) return;
      parts.push(key + '=' + value);
    });
    parts.sort();
    return parts.join('&');
  }

  function clearBadgeFor(control) {
    var name = control.name || control.getAttribute('data-mirror');
    if (!name) return;
    var holder = document.querySelector('[data-check="' + name + '"]');
    if (holder) renderBadge(holder, '');
  }

  function checkTask(button) {
    var form = button.form;
    var url = button.getAttribute('formaction');
    if (!form || !url || typeof fetch !== 'function') return false;
    var before = formSnapshot(form);
    button.disabled = true;
    fetch(url, {
      method: 'POST',
      body: new FormData(form),
      credentials: 'same-origin',
      headers: {'X-CSRFToken': csrf(form), 'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (formSnapshot(form) !== before) return;
      var checks = data.checks || {};
      Object.keys(checks).forEach(function (prefix) {
        var holder = document.querySelector('[data-check="' + prefix + '"]');
        if (holder) renderBadge(holder, checks[prefix]);
      });
      toast(data.ok !== false, data.message || 'Проверено');
    }).catch(function () {
      toast(false, 'Не удалось проверить — попробуйте ещё раз');
    }).then(function () { button.disabled = false; });
    return true;
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-check-task]').forEach(function (button) {
      button.addEventListener('click', function (e) {
        if (checkTask(button)) e.preventDefault();
      });
    });

    var answers = document.getElementById('answers-form');
    if (answers) {
      answers.addEventListener('input', function (e) { clearBadgeFor(e.target); });
      answers.addEventListener('change', function (e) { clearBadgeFor(e.target); });
    }

    document.querySelectorAll('[data-photo-submit]').forEach(function (b) { b.hidden = true; });
    document.querySelectorAll('[data-photo-input]').forEach(function (input) {
      input.addEventListener('change', function () {
        if (!(input.files && input.files.length && input.form)) return;
        var go = function () { input.form.submit(); };
        if (answers && window.EgorAutosave && EgorAutosave.autosave) {
          Promise.resolve(EgorAutosave.autosave(answers)).then(go).catch(go);
        } else {
          go();
        }
      });
    });

    var button = document.getElementById('submit-assignment');
    if (!button) return;
    button.addEventListener('click', function (e) {
      var cards = document.querySelectorAll('[data-task-card]');
      var empty = [];
      cards.forEach(function (card) {
        if (!cardAnswered(card)) {
          var number = (card.id || '').replace('task-', '');
          if (number) empty.push(number);
        }
      });
      var text = 'Отправить работу на проверку? После этого изменить ответы будет нельзя.';
      if (empty.length === cards.length && cards.length) {
        text = 'Вы не ответили ни на одну задачу. Всё равно отправить на проверку?';
      } else if (empty.length) {
        text = 'Без ответа: № ' + empty.join(', ') + '. ' + text;
      }
      if (!window.confirm(text)) e.preventDefault();
    });
  });
})();
