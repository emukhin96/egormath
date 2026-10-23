/* Проверка листка по задачам (review_tasks.html, макет D_Review): оценка
   всей группе ответов «Всем N», клавиши 1–8 ставят оценку выбранному
   ученику, ↑/↓ — соседний ученик; счётчик очереди и «Оценено» в шапке
   пересчитываются по нажатым оценкам. Оценку одному ученику сохраняет общий
   обработчик [data-grade] из teacher_progress.js. */
(function () {
  'use strict';
  var main = document.querySelector('[data-group-grade-url]');
  if (!main) return;
  var selected = null;
  function select(row) {
    if (selected) selected.classList.remove('is-selected');
    selected = row;
    if (row) row.classList.add('is-selected');
  }
  function press(button, on) {
    var value = String(on);
    if (button.getAttribute('aria-pressed') !== value) button.setAttribute('aria-pressed', value);
  }
  // Оценка — нажатая кнопка шкалы или старая отметка «Выполнено» (data-done),
  // как на сервере (review_tasks.is_graded)
  function gradeOf(row) {
    var pressed = row.querySelector('[data-grade][aria-pressed="true"]');
    return pressed ? pressed.dataset.grade : row.hasAttribute('data-done') ? 'done' : '';
  }
  function recount() {
    var rows = Array.from(main.querySelectorAll('[data-review-row]'));
    var left = rows.filter(function (row) { return !gradeOf(row); }).length;
    var queue = document.querySelector('[data-queue-left="' + main.dataset.item + '"]');
    if (queue) queue.textContent = left;
    var graded = document.querySelector('[data-review-graded]');
    if (graded) {
      var before = Number(main.dataset.rows) - Number(main.dataset.pending);
      graded.textContent = Number(graded.dataset.base) - before + rows.length - left;
    }
    // Шкала группы горит, когда у всех в группе одна оценка
    main.querySelectorAll('[data-review-group]').forEach(function (group) {
      var grades = new Set(Array.from(group.querySelectorAll('[data-review-row]')).map(gradeOf));
      var one = grades.size === 1 ? grades.values().next().value : '';
      group.querySelectorAll('[data-group-value]').forEach(function (button) {
        press(button, one !== '' && button.dataset.groupValue === one);
      });
    });
  }
  new MutationObserver(recount).observe(main, {subtree: true, attributes: true, attributeFilter: ['aria-pressed']});

  main.addEventListener('click', async function (e) {
    var row = e.target.closest('[data-review-row]');
    if (row) select(row);
    var button = e.target.closest('[data-group-value]');
    if (!button) return;
    var scale = button.closest('[data-group-grade]');
    if (scale.dataset.busy) return;
    scale.dataset.busy = '1';
    try {
      var data = new FormData();
      data.set('grade', button.dataset.groupValue);
      data.set('assignments', scale.dataset.members);
      data.set('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);
      var response = await fetch(main.dataset.groupGradeUrl, {method: 'POST', body: data, headers: {'Accept': 'application/json'}});
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Не удалось сохранить оценку');
      var urls = new Set(result.urls.map(function (url) { return new URL(url, location.href).href; }));
      main.querySelectorAll('[data-grade-url]').forEach(function (target) {
        if (!urls.has(new URL(target.dataset.gradeUrl, location.href).href)) return;
        target.querySelectorAll('[data-grade]').forEach(function (b) { press(b, b.dataset.grade === result.grade); });
      });
      scale.querySelectorAll('.is-suggested').forEach(function (b) { b.classList.remove('is-suggested'); });
      if (window.EgorAutosave) EgorAutosave.showSaved(true, result.message);
    } catch (error) {
      if (window.EgorAutosave) EgorAutosave.showSaved(false, error.message);
    } finally {
      delete scale.dataset.busy;
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey || document.querySelector('dialog[open]')) return;
    if (e.target.closest && e.target.closest('input, textarea, select, math-field, [contenteditable]')) return;
    var rows = Array.from(main.querySelectorAll('[data-review-row]'));
    if (!rows.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      var index = rows.indexOf(selected);
      index = e.key === 'ArrowDown' ? Math.min(rows.length - 1, index + 1) : Math.max(0, index - 1);
      select(rows[index]);
      rows[index].focus({preventScroll: true});
      rows[index].scrollIntoView({block: 'nearest'});
      e.preventDefault();
      return;
    }
    var number = parseInt(e.key, 10);
    if (!selected || !(number >= 1 && number <= 8)) return;
    var grade = selected.querySelectorAll('[data-grade]')[number - 1];
    if (grade) { grade.click(); e.preventDefault(); }
  });
  recount();
})();
