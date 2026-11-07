/* Проверка работы, вариант A «Лента» (выбор Егора 07.11, замечание Z3).
   1) Условие задачи свёрнуто до двух строк: клик по нему раскрывает и
      сворачивает (у коротких условий сворачивать нечего — без класса).
   2) Карта задач справа красится по выставленной оценке: следим за
      aria-pressed кнопок шкалы, которую обновляет teacher_progress.js. */
(function () {
  'use strict';

  function clampAll() {
    document.querySelectorAll('.review-task .task-copy').forEach(function (copy) {
      if (copy.dataset.clampReady) return;
      copy.dataset.clampReady = '1';
      copy.classList.add('is-clamped');
      if (copy.scrollHeight <= copy.clientHeight + 2) {
        copy.classList.remove('is-clamped');
        return;
      }
      copy.setAttribute('role', 'button');
      copy.setAttribute('tabindex', '0');
      copy.setAttribute('aria-expanded', 'false');
      copy.title = 'Показать условие целиком';
      var toggle = function () {
        var open = copy.classList.toggle('is-clamped') === false;
        copy.setAttribute('aria-expanded', String(open));
        copy.title = open ? 'Свернуть условие' : 'Показать условие целиком';
      };
      copy.addEventListener('click', function (e) {
        if (e.target.closest('a, button, img')) return;
        toggle();
      });
      copy.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
    });
  }

  function syncMap(task) {
    var number = task.dataset.reviewTask;
    var cell = document.querySelector('[data-review-map="' + number + '"]');
    if (!cell) return;
    var pressed = task.querySelector('.grade-scale [data-grade][aria-pressed="true"]');
    cell.dataset.mapGrade = pressed ? pressed.dataset.grade : '';
  }

  function init() {
    // Формулы KaTeX рендерятся после загрузки — меряем высоту после них
    setTimeout(clampAll, 300);
    var observer = new MutationObserver(function (records) {
      records.forEach(function (r) {
        var task = r.target.closest && r.target.closest('[data-review-task]');
        if (task) syncMap(task);
      });
    });
    document.querySelectorAll('[data-review-task]').forEach(function (task) {
      observer.observe(task, {attributes: true, subtree: true, attributeFilter: ['aria-pressed']});
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
