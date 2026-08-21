/* Конструктор листка: drag-and-drop, кликабельные звёзды, тумблер
   ответов/решений. Автосохранение форм — в общем autosave.js. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var autosave = window.EgorAutosave.autosave;
    var showSaved = window.EgorAutosave.showSaved;

    // Переименование листка: обновляем заголовок страницы на лету
    var titleInput = document.querySelector(
      '.ws-title-edit form[data-autosave] input[name=title]');
    if (titleInput) {
      titleInput.addEventListener('input', function () {
        var h1 = document.querySelector('.ws-title-edit h1');
        if (h1 && titleInput.value.trim()) {
          h1.childNodes[0].textContent = titleInput.value.trim() + ' ';
        }
      });
    }

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
        if (reset) reset.hidden = value === null;
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
        reset.addEventListener('click', function () { setStars(null); });
      }
    });

    // --- Тумблер «ответы и решения» ---
    var toggle = document.getElementById('toggle-answers');
    var list = document.getElementById('ws-items');
    if (toggle && list) {
      var KEY = 'ws-show-answers';
      function apply() {
        list.classList.toggle('show-answers', toggle.checked);
        try { localStorage.setItem(KEY, toggle.checked ? '1' : ''); } catch (e) {}
      }
      try { toggle.checked = localStorage.getItem(KEY) === '1'; } catch (e) {}
      apply();
      toggle.addEventListener('change', apply);
    }

    // --- Перетаскивание элементов ---
    if (list && typeof Sortable !== 'undefined') {
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
