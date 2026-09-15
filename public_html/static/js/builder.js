/* Конструктор листка: drag-and-drop, кликабельные звёзды, тумблер
   ответов/решений. Автосохранение форм — в общем autosave.js. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var autosave = window.EgorAutosave.autosave;
    var showSaved = window.EgorAutosave.showSaved;

    document.querySelectorAll('[data-undo-dismiss]').forEach(function (button) {
      button.addEventListener('click', function () {
        var bar = button.closest('.undo-bar');
        if (bar) bar.hidden = true;
      });
    });

    // --- Заголовок и подзаголовок: редактирование кликом по тексту ---
    document.querySelectorAll('.ws-editable').forEach(function (span) {
      var input = document.querySelector(
        '[data-edit-input="' + span.dataset.edit + '"]');
      if (!input) return;
      var form = input.form
        || document.getElementById(input.getAttribute('form'));
      var finishing = false;

      function open() {
        span.hidden = true;
        input.hidden = false;
        input.focus();
        input.select();
      }

      function render(value) {
        span.textContent = value || span.dataset.placeholder || '';
      }

      function finish(save) {
        if (finishing) return;
        finishing = true;
        var value = input.value.trim();
        var mustKeep = input.required && !value;
        if (save && !mustKeep && value !== span.textContent.trim()) {
          input.value = value;
          render(value);
          if (form && window.EgorAutosave) window.EgorAutosave.autosave(form);
        } else {
          // Откат к текущему отображаемому значению
          var shown = span.textContent.trim();
          input.value = shown === span.dataset.placeholder ? '' : shown;
        }
        input.hidden = true;
        span.hidden = false;
        finishing = false;
      }

      span.addEventListener('click', open);
      span.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); finish(true); }
        if (e.key === 'Escape') { e.preventDefault(); finish(false); }
      });
      input.addEventListener('blur', function () { finish(true); });
    });

    // --- Кликабельные звёзды ---
    function paintStars(widget, count) {
      widget.querySelectorAll('.ws-star').forEach(function (btn) {
        btn.classList.toggle('on', Number(btn.dataset.value) <= count);
      });
      widget.dataset.effective = count;
    }

    document.querySelectorAll('.ws-stars').forEach(function (widget) {
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
