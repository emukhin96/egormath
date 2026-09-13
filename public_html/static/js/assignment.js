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
    var controls = card.querySelectorAll('input:not([type=hidden]):not([type=file]), textarea, select, math-field');
    for (var i = 0; i < controls.length; i++) {
      var c = controls[i];
      if (c.type === 'checkbox') { if (c.checked) return true; continue; }
      if ((c.value || '').trim()) return true;
    }
    return !!card.querySelector('[data-photos] img');
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

  function badgeKeys(control) {
    /* data-check — префикс задачи (task123) или слот (task123_s1);
       у поля суффикс _number/_text/_low/_high, у слота — _none/_0. */
    var name = control.name || control.getAttribute('data-mirror') || '';
    if (!name) return [];
    var keys = [name];
    var stripped = name.replace(/_(?:none|number|text|low|high|\d+)$/, '');
    if (stripped && stripped !== name) keys.push(stripped);
    return keys;
  }

  function clearHolder(holder) {
    if (!holder) return;
    if (window.EgorCheckBadge) EgorCheckBadge.render(holder, '');
    else { holder.dataset.status = ''; holder.textContent = ''; }
  }

  function clearBadgeFor(control) {
    badgeKeys(control).forEach(function (key) {
      clearHolder(document.querySelector('[data-check="' + key + '"]'));
    });
    var slot = control.closest && control.closest('.mask-slot');
    if (slot) clearHolder(slot.querySelector('[data-check]'));
  }

  function checkTask(button) {
    var form = button.form;
    var url = button.getAttribute('formaction');
    if (!form || !url || typeof fetch !== 'function') return false;
    var before = formSnapshot(form);
    button.disabled = true;
    var body = new FormData(form);
    if (button.name) body.set(button.name, button.value);
    var enqueue = window.EgorAutosave?.enqueue || function (_, operation) { return operation(); };
    enqueue(form, function () { return fetch(url, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: {'X-CSRFToken': csrf(form), 'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (r) { return r.json(); }); }).then(function (data) {
      if (formSnapshot(form) !== before) return;
      /* Бейджи (check_badge.js) — по полям задачи и по слотам маски */
      if (window.EgorCheckBadge) EgorCheckBadge.apply(document, data.checks || {});
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
          Promise.resolve(EgorAutosave.autosave(answers)).then(function (ok) {
            if (ok) go();
          });
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
