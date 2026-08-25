/* Нейрогенерация ответов/решений: общий fetch и привязка кнопок/ссылок.
   Эндпоинт — window.NEURO_SOLVE_URL (POST JSON). Ничего не пишет
   в базу, пока в теле нет apply:true (это делает конструктор листка).
   Слушатель на document: работает даже если DOMContentLoaded уже прошёл. */
(function () {
  'use strict';

  var LABEL = 'Добавить AI-решение';
  var BUSY = 'Генерация…';

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el && el.value) return el.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) {
      EgorAutosave.showSaved(ok, message);
      return;
    }
    if (!ok) window.alert(message);
  }

  function solve(payload) {
    var url = window.NEURO_SOLVE_URL;
    if (!url) {
      return Promise.reject(new Error(
        'Нейрогенерация не подключена. Обновите страницу.'));
    }
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify(payload),
    }).then(function (response) {
      return response.json().then(function (result) {
        if (!response.ok) {
          throw new Error(result.error || 'Ошибка генерации.');
        }
        return result;
      }, function () {
        throw new Error('Ошибка генерации (HTTP ' + response.status + ').');
      });
    });
  }

  function setValue(el, value) {
    if (!el || value == null) return;
    el.value = value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
  }

  function confirmOverwrite(hasExisting) {
    if (!hasExisting) return true;
    return window.confirm(
      'Заменить существующий ответ или решение черновиком нейросети?');
  }

  function withBusy(el, work) {
    var label = el.textContent;
    el.setAttribute('aria-busy', 'true');
    if (el.tagName === 'BUTTON') el.disabled = true;
    el.textContent = BUSY;
    return work().then(function (result) {
      el.textContent = label;
      return result;
    }).catch(function (err) {
      el.textContent = label;
      toast(false, err.message || 'Ошибка генерации.');
      throw err;
    }).finally(function () {
      el.removeAttribute('aria-busy');
      if (el.tagName === 'BUTTON') el.disabled = false;
    });
  }

  function collectDetail() {
    var textEl = document.querySelector(
      'form[data-autosave] textarea[name="text_latex"]');
    var text = textEl ? textEl.value : '';
    var blocks = document.querySelectorAll('.subitem-block');
    var subitems = [];
    blocks.forEach(function (block) {
      var field = block.querySelector(
        '.subitem-edit-form textarea[name="text_latex"]');
      subitems.push(field ? field.value : '');
    });
    return {text: text, subitems: subitems};
  }

  function fillDetail(result) {
    var blocks = document.querySelectorAll('.subitem-block');
    if (blocks.length) {
      blocks.forEach(function (block, i) {
        var box = block.querySelector('details');
        if (box) box.open = true;
        setValue(block.querySelector(
          '.subitem-edit-form textarea[name="answer_latex"]'),
          (result.subitem_answers || [])[i]);
        setValue(block.querySelector(
          '.subitem-edit-form textarea[name="solution_latex"]'),
          (result.subitem_solutions || [])[i]);
      });
      return;
    }
    var answerBox = document.getElementById('qa_answer');
    var solutionBox = document.getElementById('qa_solution');
    if (answerBox && answerBox.closest('details')) {
      answerBox.closest('details').open = true;
    }
    if (solutionBox && solutionBox.closest('details')) {
      solutionBox.closest('details').open = true;
    }
    setValue(answerBox, result.answer);
    setValue(solutionBox, result.solution);
  }

  function detailHasExisting() {
    var filled = false;
    document.querySelectorAll(
      '.subitem-edit-form textarea[name="answer_latex"], ' +
      '.subitem-edit-form textarea[name="solution_latex"], ' +
      '#qa_answer, #qa_solution'
    ).forEach(function (el) {
      if (el.value.trim()) filled = true;
    });
    return filled;
  }

  function collectForm() {
    var textEl = document.getElementById('id_text_latex');
    var text = textEl ? textEl.value : '';
    var subitems = [];
    document.querySelectorAll(
      'table.formset[data-formset="subitems"] tr.formset-row'
    ).forEach(function (row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) return;
      var field = row.querySelector('textarea[name$="-text_latex"]');
      if (field && field.name.indexOf('__prefix__') === -1) {
        subitems.push(field.value);
      }
    });
    return {text: text, subitems: subitems};
  }

  function fillForm(result) {
    var rows = [];
    document.querySelectorAll(
      'table.formset[data-formset="subitems"] tr.formset-row'
    ).forEach(function (row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) return;
      var field = row.querySelector('textarea[name$="-text_latex"]');
      if (field && field.name.indexOf('__prefix__') === -1) {
        rows.push(row);
      }
    });
    if (rows.length) {
      rows.forEach(function (row, i) {
        setValue(row.querySelector('textarea[name$="-answer_latex"]'),
          (result.subitem_answers || [])[i]);
        setValue(row.querySelector('textarea[name$="-solution_latex"]'),
          (result.subitem_solutions || [])[i]);
      });
      return;
    }
    setValue(document.getElementById('id_answer_latex'), result.answer);
    setValue(document.getElementById('id_solution_latex'), result.solution);
  }

  function formHasExisting() {
    var filled = false;
    ['id_answer_latex', 'id_solution_latex'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.value.trim()) filled = true;
    });
    document.querySelectorAll(
      'table.formset[data-formset="subitems"] textarea[name$="-answer_latex"], ' +
      'table.formset[data-formset="subitems"] textarea[name$="-solution_latex"]'
    ).forEach(function (el) {
      if (el.name.indexOf('__prefix__') === -1 && el.value.trim()) {
        filled = true;
      }
    });
    return filled;
  }

  function payloadFor(el, collected) {
    if (collected && collected.text && collected.text.trim()) {
      return collected;
    }
    if (el.dataset.taskId) {
      return {task_id: el.dataset.taskId};
    }
    return collected || {};
  }

  function applyTask(el) {
    var overwrite = el.dataset.hasAnswer === '1';
    if (!confirmOverwrite(overwrite)) return Promise.resolve();
    return withBusy(el, function () {
      return solve({
        task_id: el.dataset.taskId,
        apply: true,
        overwrite: overwrite,
      });
    }).then(function () {
      toast(true, 'Черновик записан — проверьте задачу');
      window.location.reload();
    });
  }

  function onClick(ev) {
    var el = ev.target.closest('[data-neuro]');
    if (!el) return;
    ev.preventDefault();
    var kind = el.dataset.neuro;
    if (kind === 'task-detail') {
      if (!confirmOverwrite(detailHasExisting())) return;
      withBusy(el, function () {
        var payload = payloadFor(el, collectDetail());
        if (el.dataset.taskId) {
          payload.task_id = el.dataset.taskId;
          payload.apply = true;
          payload.overwrite = detailHasExisting();
        }
        return solve(payload).then(fillDetail);
      }).then(function () {
        toast(true, 'Черновик в полях — проверьте и поправьте');
      }).catch(function () {});
      return;
    }
    if (kind === 'task-form') {
      if (!confirmOverwrite(formHasExisting())) return;
      withBusy(el, function () {
        return solve(payloadFor(el, collectForm())).then(fillForm);
      }).then(function () {
        toast(true, 'Черновик в полях — проверьте перед сохранением');
      }).catch(function () {});
      return;
    }
    if (kind === 'apply') {
      applyTask(el).catch(function () {});
      return;
    }
    if (kind === 'apply-missing') {
      var queue = Array.prototype.slice.call(
        document.querySelectorAll('[data-neuro="apply"][data-has-answer=""]'));
      if (!queue.length) {
        toast(false, 'Нет задач без ответа');
        return;
      }
      var done = 0;
      var failed = 0;
      withBusy(el, function () {
        return queue.reduce(function (chain, item) {
          return chain.then(function () {
            el.textContent = 'Генерация ' + (done + 1) + '/' +
              queue.length + '…';
            return solve({
              task_id: item.dataset.taskId,
              apply: true,
              overwrite: false,
            }).then(function () {
              done += 1;
            }).catch(function () {
              failed += 1;
            });
          });
        }, Promise.resolve());
      }).then(function () {
        if (failed) {
          toast(false, 'Не удалось: ' + failed + ' из ' + queue.length);
        } else {
          toast(true, 'Черновики записаны — проверьте задачи');
        }
        window.location.reload();
      }).catch(function () {});
    }
  }

  document.addEventListener('click', onClick);

  window.EgorNeuro = {
    solve: solve,
    label: LABEL,
    withBusy: withBusy,
    toast: toast,
  };
})();
