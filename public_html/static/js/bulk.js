/* Массовое выделение строк в списках (задачи, листки).
   Чекбоксы строк привязаны к форме массового действия через form="…";
   панель действий появляется, когда выбрана хотя бы одна строка.
   Обработчики делегированы, поэтому строки, подгруженные живым поиском,
   работают без повторной инициализации; EgorBulk.init() пересчитывает
   панель после подмены результатов. */
(function () {
  'use strict';

  function positionBar() {
    var header = document.querySelector('.topbar');
    var height = header && getComputedStyle(header).position === 'sticky' ? header.getBoundingClientRect().height : 0;
    document.documentElement.style.setProperty('--bulk-top', height + 'px');
  }

  function boxesFor(form) {
    return Array.prototype.slice.call(
      document.querySelectorAll('input.row-select[form="' + form.id + '"]'));
  }

  function refresh(form) {
    var boxes = boxesFor(form);
    var checked = boxes.filter(function (b) { return b.checked; });
    form.hidden = checked.length === 0;
    var count = form.querySelector('[data-bulk-count]');
    if (count) count.textContent = 'Выбрано: ' + checked.length;
    document.querySelectorAll('input[data-bulk-all="' + form.id + '"]').forEach(function (all) {
      all.checked = boxes.length > 0 && checked.length === boxes.length;
      all.indeterminate = checked.length > 0 && checked.length < boxes.length;
    });
  }

  function init() {
    positionBar();
    document.querySelectorAll('form[data-bulk]').forEach(refresh);
  }

  document.addEventListener('change', function (event) {
    var box = event.target;
    if (box.matches('input.row-select[form]')) {
      var form = document.getElementById(box.getAttribute('form'));
      if (form) refresh(form);
    } else if (box.matches('input[data-bulk-all]')) {
      var target = document.getElementById(box.dataset.bulkAll);
      if (!target) return;
      boxesFor(target).forEach(function (b) { b.checked = box.checked; });
      refresh(target);
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    var header = document.querySelector('.topbar');
    if (header && window.ResizeObserver) new ResizeObserver(positionBar).observe(header);
    window.addEventListener('resize', positionBar);
    init();
  });

  window.EgorBulk = {init: init};
})();
