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

    function showAnswers() {
      if (toggle && !toggle.checked) {
        toggle.checked = true;
        form.classList.add('show-answers');
      }
    }

    /* --- Нейрогенерация ответов/решений (черновики в поля формы) --- */
    var solveDataEl = document.getElementById('import-solve-data');
    var solveData = solveDataEl ? JSON.parse(solveDataEl.textContent) : {};
    var csrf = form.querySelector('[name="csrfmiddlewaretoken"]').value;

    function setField(name, value) {
      if (!value) return;
      var field = form.querySelector('[name="' + name + '"]');
      if (field) field.value = value;
    }

    function solveRow(index) {
      var data = solveData[index];
      if (!data) return Promise.resolve();
      return fetch(window.IMPORT_SOLVE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(data),
      }).then(function (response) {
        return response.json().then(function (result) {
          if (!response.ok) {
            throw new Error(result.error || 'Ошибка генерации.');
          }
          setField('answer_' + index, result.answer);
          setField('solution_' + index, result.solution);
          (result.subitem_answers || []).forEach(function (value, j) {
            setField('answer_' + index + '_' + j, value);
          });
          (result.subitem_solutions || []).forEach(function (value, j) {
            setField('solution_' + index + '_' + j, value);
          });
          showAnswers();
        });
      });
    }

    document.querySelectorAll('.neuro-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        btn.disabled = true;
        btn.textContent = 'генерация…';
        solveRow(btn.dataset.index).then(function () {
          btn.textContent = '✨ сгенерировать';
        }).catch(function (err) {
          btn.textContent = '✨ сгенерировать';
          alert(err.message);
        }).finally(function () {
          btn.disabled = false;
        });
      });
    });

    var bulkSolve = document.getElementById('bulk-solve');
    if (bulkSolve) {
      bulkSolve.addEventListener('click', function () {
        var queue = selected().map(function (box) {
          return box.dataset.index;
        });
        if (!queue.length) return;
        var label = bulkSolve.textContent;
        var done = 0;
        var failed = 0;
        bulkSolve.disabled = true;
        // Последовательно, по одной задаче — без параллельной пачки запросов
        queue.reduce(function (chain, index) {
          return chain.then(function () {
            bulkSolve.textContent =
              'Генерация ' + (done + 1) + '/' + queue.length + '…';
            return solveRow(index).then(function () {
              done += 1;
            }).catch(function () {
              failed += 1;
            });
          });
        }, Promise.resolve()).then(function () {
          bulkSolve.textContent = label;
          bulkSolve.disabled = false;
          if (failed) {
            alert('Не удалось сгенерировать: ' + failed + ' из ' +
                  queue.length + '. Проверьте настройку GEMINI_API_KEY.');
          }
        });
      });
    }
  });
})();
