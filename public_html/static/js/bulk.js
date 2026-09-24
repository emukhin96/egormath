/* Массовое выделение строк в списках (задачи, листки, импорт).
   Чекбоксы строк привязаны к форме массового действия через form="…";
   панель действий появляется, когда выбрана хотя бы одна строка.
   Режим «все найденные» (импорт задачника): кнопка [data-bulk-filtered]
   переводит скрытое поле selection_scope в filtered, [data-bulk-clear]
   снимает выделение. Обработчики делегированы, поэтому строки,
   подгруженные живым поиском, работают без повторной инициализации;
   EgorBulk.init() пересчитывает панели после подмены результатов. */
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

  function controls(form) {
    return {
      scope: form.querySelector('[name="selection_scope"]'),
      filteredButton: document.querySelector('[data-bulk-filtered="' + form.id + '"]'),
      clearButton: document.querySelector('[data-bulk-clear="' + form.id + '"]'),
    };
  }

  function refresh(form) {
    var boxes = boxesFor(form);
    var c = controls(form);
    var checked = boxes.filter(function (b) { return b.checked; });
    var filtered = !!(c.scope && c.scope.value === 'filtered' && c.filteredButton);
    var total = filtered ? Number(c.filteredButton.dataset.filteredCount) : checked.length;
    form.hidden = total === 0;
    var count = form.querySelector('[data-bulk-count]');
    if (count) count.textContent = 'Выбрано: ' + total + (filtered ? ' (все найденные)' : '');
    if (c.filteredButton) c.filteredButton.disabled = filtered;
    if (c.clearButton) c.clearButton.hidden = total === 0;
    document.querySelectorAll('input[data-bulk-all="' + form.id + '"]').forEach(function (all) {
      all.checked = boxes.length > 0 && checked.length === boxes.length;
      all.indeterminate = checked.length > 0 && checked.length < boxes.length;
    });
  }

  function setScope(form, value) {
    var scope = form.querySelector('[name="selection_scope"]');
    if (scope) scope.value = value;
  }

  function init() {
    positionBar();
    document.querySelectorAll('form[data-bulk]').forEach(refresh);
  }

  document.addEventListener('change', function (event) {
    var box = event.target;
    if (box.matches('input.row-select[form]')) {
      var form = document.getElementById(box.getAttribute('form'));
      if (!form) return;
      setScope(form, 'page');
      refresh(form);
    } else if (box.matches('input[data-bulk-all]')) {
      var target = document.getElementById(box.dataset.bulkAll);
      if (!target) return;
      setScope(target, 'page');
      boxesFor(target).forEach(function (b) { b.checked = box.checked; });
      refresh(target);
    }
  });

  document.addEventListener('click', function (event) {
    var filteredButton = event.target.closest('[data-bulk-filtered]');
    if (filteredButton) {
      var form = document.getElementById(filteredButton.dataset.bulkFiltered);
      if (!form) return;
      setScope(form, 'filtered');
      boxesFor(form).forEach(function (b) { b.checked = true; });
      refresh(form);
      return;
    }
    var clearButton = event.target.closest('[data-bulk-clear]');
    if (clearButton) {
      var target = document.getElementById(clearButton.dataset.bulkClear);
      if (!target) return;
      setScope(target, 'page');
      boxesFor(target).forEach(function (b) { b.checked = false; });
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
