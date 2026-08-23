/* Предпросмотр импорта .tex: выделение задач и массовое назначение
   класса/темы/звёзд. Значения копируются в поля выделенных строк —
   на сервер уходят обычные поля grade_N/topic_N/stars_N. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('import-create-form');
    if (!form) return;
    var panel = document.getElementById('import-bulk');
    var count = document.getElementById('bulk-count');
    var selectAll = document.getElementById('select-all');
    var boxes = Array.prototype.slice.call(
      form.querySelectorAll('.row-select'));

    function selected() {
      return boxes.filter(function (b) { return b.checked; });
    }

    function refresh() {
      var n = selected().length;
      panel.hidden = n === 0;
      count.textContent = n;
      if (selectAll) {
        selectAll.checked = n > 0 && n === boxes.length;
      }
    }

    boxes.forEach(function (b) { b.addEventListener('change', refresh); });
    if (selectAll) {
      selectAll.addEventListener('change', function () {
        boxes.forEach(function (b) { b.checked = selectAll.checked; });
        refresh();
      });
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
  });
})();
