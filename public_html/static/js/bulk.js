/* Массовое выделение строк в списках (задачи, листки).
   Чекбоксы строк привязаны к форме массового действия через form="…";
   панель действий появляется, когда выбрана хотя бы одна строка. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-bulk]').forEach(function (form) {
      var boxes = Array.prototype.slice.call(
        document.querySelectorAll(
          'input.row-select[form="' + form.id + '"]'));
      var all = document.querySelector(
        'input[data-bulk-all="' + form.id + '"]');
      var count = form.querySelector('[data-bulk-count]');
      if (!boxes.length) return;

      function refresh() {
        var checked = boxes.filter(function (b) { return b.checked; });
        form.hidden = checked.length === 0;
        if (count) count.textContent = 'Выбрано: ' + checked.length;
        if (all) all.checked = checked.length === boxes.length;
      }

      boxes.forEach(function (box) {
        box.addEventListener('change', refresh);
      });
      if (all) {
        all.addEventListener('change', function () {
          boxes.forEach(function (box) { box.checked = all.checked; });
          refresh();
        });
      }
      refresh();
    });
  });
})();
