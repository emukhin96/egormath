/* Конструктор листка: drag-and-drop, кликабельные звёзды, тумблер
   ответов/решений. Автосохранение форм — в общем autosave.js. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var autosave = window.EgorAutosave.autosave;
    var showSaved = window.EgorAutosave.showSaved;

    // --- Заголовок и подзаголовок: редактирование кликом по тексту ---
    document.querySelectorAll('.ws-editable').forEach(function (span) {
      var input = document.querySelector(
        '[data-edit-input="' + span.dataset.edit + '"]');
      if (!input) return;
      var form = input.form
        || document.getElementById(input.getAttribute('form'));
      var saved = input.value, revision = 0;
      span.addEventListener('input', function () { revision += 1; });
      span.addEventListener('keydown', function (e) {
        if (e.isComposing) return;
        if (e.key === 'Enter') { e.preventDefault(); span.blur(); }
        if (e.key === 'Escape') {
          e.preventDefault(); span.textContent = input.value; span.blur();
        }
      });
      span.addEventListener('blur', function () {
        var value = span.textContent.replace(/\s+/g, ' ').trim();
        var limit = Number(input.getAttribute('maxlength'));
        if ((input.required && !value) || value.length > limit) {
          span.textContent = input.value;
          showSaved(false, !value ? 'Название не может быть пустым' : 'Слишком длинный текст');
          return;
        }
        span.textContent = value;
        if (value === input.value) return;
        input.value = value;
        var current = ++revision;
        autosave(form).then(function (ok) {
          if (ok) saved = value;
          if (!ok && current === revision) {
            input.value = saved;
            span.textContent = saved;
          }
          if (ok && span.dataset.edit === 'title') {
            document.title = value + ' — Математика';
            var heading = document.querySelector('#context-sidebar h2');
            if (heading) heading.textContent = value;
          }
        });
      });
    });

    // --- Кликабельные звёзды ---
    function paintStars(widget, count) {
      widget.querySelectorAll('.ws-star').forEach(function (btn) {
        btn.classList.toggle('on', Number(btn.dataset.value) <= count);
      });
      widget.dataset.effective = count;
    }

    function initStars() {
      document.querySelectorAll('.ws-stars:not([data-initialized])').forEach(function (widget) {
        widget.dataset.initialized = '1';
        var form = document.getElementById(widget.dataset.form);
        if (!form) return;
        var hidden = form.querySelector('input[name=stars]');
        var reset = document.querySelector(
          '.ws-star-reset[data-form="' + widget.dataset.form + '"]');

        function setStars(value) {
          hidden.value = value === null ? '' : String(value);
          paintStars(widget, value === null ? Number(reset.dataset.base) : value);
          autosave(form);
        }

        widget.querySelectorAll('.ws-star').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var value = Number(btn.dataset.value);
            // Клик по текущему значению — на звезду меньше (так можно дойти до 0)
            if (value === Number(widget.dataset.effective)) value -= 1;
            setStars(value);
          });
        });
        if (reset) {
          reset.addEventListener('click', function () { setStars(0); });
        }
      });
    }
    initStars();
    document.addEventListener('worksheet:updated', initStars);

    // Тумблер ответов — answers-toggle.js (тот же #toggle-answers / #ws-items).

    // --- Перетаскивание элементов ---
    var list = document.getElementById('ws-items');
    if (list && list.dataset.reorderUrl && typeof Sortable !== 'undefined') {
      var csrf = document.querySelector('#ws-items input[name=csrfmiddlewaretoken]');
      Sortable.create(list, {
        handle: '.drag-handle',
        animation: 150,
        ghostClass: 'ws-ghost',
        onEnd: function () {
          var ids = Array.prototype.map.call(
            list.querySelectorAll('.ws-item'),
            function (el) { return el.dataset.id; });
          var body = new URLSearchParams();
          body.append('order', ids.join(','));
          fetch(list.dataset.reorderUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': csrf ? csrf.value : '',
                      'Content-Type': 'application/x-www-form-urlencoded'},
            body: body.toString(),
          }).then(function (r) {
            if (!r.ok) { location.reload(); return; }
            if (list.dataset.reorderReload === '1') { location.reload(); return; }
            showSaved(true, '');
            // Перенумеровать задачи (рубрики и тексты без номера)
            var n = 0;
            list.querySelectorAll('.ws-item .ws-num').forEach(function (el) {
              n += 1; el.textContent = n + '.';
            });
          }).catch(function () { location.reload(); });
        },
      });
    }
  });
})();
