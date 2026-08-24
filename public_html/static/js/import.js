/* Предпросмотр импорта .tex. Выделение строк — общий контракт bulk.js
   (форма import-bulk-form); здесь — действия над выделенными строками:
   массовое назначение класса/темы/звёзд (значения копируются в поля
   строк — на сервер уходят обычные grade_N/topic_N/stars_N), пометка
   «удалить из импорта» (skip_N) и тумблер показа ответов/решений. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('import-create-form');
    if (!form) return;
    var bulkForm = document.getElementById('import-bulk-form');
    var boxes = Array.prototype.slice.call(
      document.querySelectorAll('.row-select[form="import-bulk-form"]'));

    function selected() {
      return boxes.filter(function (b) { return b.checked; });
    }

    document.getElementById('bulk-apply').addEventListener('click', function () {
      var values = {
        grade: document.getElementById('bulk-grade').value,
        topic: document.getElementById('bulk-topic').value,
        stars: document.getElementById('bulk-stars').value,
      };
      selected().forEach(function (box) {
        var i = box.dataset.index;
        Object.keys(values).forEach(function (key) {
          if (values[key] === '') return;
          var field = form.querySelector('[name="' + key + '_' + i + '"]');
          if (field) field.value = values[key];
        });
      });
    });

    // «Удаление» из импорта — клиентская пометка: строка гаснет,
    // skip_N уходит на сервер, и тот пропускает её при создании листка
    function setSkipped(index, skipped) {
      var row = document.querySelector('[data-import-row="' + index + '"]');
      if (!row) return;
      row.classList.toggle('import-skipped', skipped);
      var flag = form.querySelector('[name="skip_' + index + '"]');
      if (flag) flag.value = skipped ? '1' : '';
      var state = row.querySelector('.import-skip-state');
      if (state) state.hidden = !skipped;
    }

    document.getElementById('bulk-skip').addEventListener('click', function () {
      selected().forEach(function (box) {
        setSkipped(box.dataset.index, true);
        box.checked = false;
      });
      // bulk.js прячет панель сам по change; диспатчим его вручную
      boxes[0].dispatchEvent(new Event('change', { bubbles: true }));
    });

    document.querySelectorAll('.import-restore').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setSkipped(btn.closest('[data-import-row]').dataset.importRow, false);
      });
    });

    var toggle = document.getElementById('toggle-import-answers');
    if (toggle) {
      toggle.addEventListener('change', function () {
        form.classList.toggle('show-answers', toggle.checked);
      });
    }
  });
})();
