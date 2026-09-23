/* Массовое выделение строк в списках (задачи, листки).
   Чекбоксы строк привязаны к форме массового действия через form="…";
   панель действий появляется, когда выбрана хотя бы одна строка. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var header = document.querySelector('.topbar');
    function positionBar() {
      var height = header && getComputedStyle(header).position === 'sticky' ? header.getBoundingClientRect().height : 0;
      document.documentElement.style.setProperty('--bulk-top', height + 'px');
    }
    positionBar();
    if (header && window.ResizeObserver) new ResizeObserver(positionBar).observe(header);
    window.addEventListener('resize', positionBar);
    document.querySelectorAll('form[data-bulk]').forEach(function (form) {
      var boxes = Array.prototype.slice.call(
        document.querySelectorAll(
          'input.row-select[form="' + form.id + '"]'));
      var allBoxes = Array.prototype.slice.call(
        document.querySelectorAll(
          'input[data-bulk-all="' + form.id + '"]'));
      var count = form.querySelector('[data-bulk-count]');
      var scope = form.querySelector('[name="selection_scope"]');
      var filteredButton = document.querySelector('[data-bulk-filtered="' + form.id + '"]');
      var clearButton = document.querySelector('[data-bulk-clear="' + form.id + '"]');
      if (!boxes.length && !filteredButton) return;

      function refresh() {
        var checked = boxes.filter(function (b) { return b.checked; });
        var filtered = scope && scope.value === 'filtered';
        var total = filtered ? Number(filteredButton.dataset.filteredCount) : checked.length;
        form.hidden = total === 0;
        if (count) count.textContent = 'Выбрано: ' + total + (filtered ? ' (все найденные)' : '');
        if (filteredButton) filteredButton.disabled = filtered;
        if (clearButton) clearButton.hidden = total === 0;
        allBoxes.forEach(function (all) {
          all.checked = boxes.length > 0 && checked.length === boxes.length;
          all.indeterminate = checked.length > 0 && checked.length < boxes.length;
        });
      }

      boxes.forEach(function (box) {
        box.addEventListener('change', function () {
          if (scope) scope.value = 'page';
          refresh();
        });
      });
      allBoxes.forEach(function (all) {
        all.addEventListener('change', function () {
          if (scope) scope.value = 'page';
          boxes.forEach(function (box) { box.checked = all.checked; });
          allBoxes.forEach(function (other) { other.checked = all.checked; });
          refresh();
        });
      });
      if (filteredButton && scope) filteredButton.addEventListener('click', function () {
        scope.value = 'filtered';
        boxes.forEach(function (box) { box.checked = true; });
        refresh();
      });
      if (clearButton) clearButton.addEventListener('click', function () {
        if (scope) scope.value = 'page';
        boxes.forEach(function (box) { box.checked = false; });
        refresh();
      });
      refresh();
    });
  });
})();
