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

  function setValue(el, value, silent) {
    // Как apply_result: пустое от модели не затирает уже заполненное поле.
    if (!el || value == null || !String(value).trim()) return false;
    el.value = value;
    // Без input автосейв на карточке не запишет черновик до проверки.
    if (!silent) {
      el.dispatchEvent(new Event('input', {bubbles: true}));
    }
    return true;
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

  function rememberForm(el, forms) {
    if (!el) return;
    var form = el.form || el.closest('form[data-autosave]');
    if (form && form.dataset.autosave && forms.indexOf(form) === -1) {
      forms.push(form);
    }
  }

  function saveFilledForms(forms) {
    // Карточка без кнопки «Сохранить»: после проверки — явный автосейв,
    // не событие input (оно писало черновик ещё до просмотра).
    if (!forms.length) return false;
    if (!window.confirm('Сохранить черновик в задачу?')) return false;
    if (!window.EgorAutosave) return false;
    forms.forEach(function (form) { EgorAutosave.autosave(form); });
    return true;
  }

  function fillDetail(result, answersOnly) {
    var forms = [];
    var blocks = document.querySelectorAll('.subitem-block');
    if (blocks.length) {
      blocks.forEach(function (block, i) {
        var box = block.querySelector('details');
        if (box) box.open = true;
        var ansEl = block.querySelector(
          '.subitem-edit-form textarea[name="answer_latex"]');
        if (!answersOnly || (ansEl && !ansEl.value.trim())) {
          if (setValue(ansEl, (result.subitem_answers || [])[i], true)) {
            rememberForm(ansEl, forms);
          }
        }
        if (!answersOnly) {
          var solEl = block.querySelector(
            '.subitem-edit-form textarea[name="solution_latex"]');
          if (setValue(solEl, (result.subitem_solutions || [])[i], true)) {
            rememberForm(solEl, forms);
          }
        }
      });
      return forms;
    }
    var answerBox = document.getElementById('qa_answer');
    var solutionBox = document.getElementById('qa_solution');
    if (answerBox && answerBox.closest('details')) {
      answerBox.closest('details').open = true;
    }
    if (!answersOnly && solutionBox && solutionBox.closest('details')) {
      solutionBox.closest('details').open = true;
    }
    if (!answersOnly || (answerBox && !answerBox.value.trim())) {
      if (setValue(answerBox, result.answer, true)) {
        rememberForm(answerBox, forms);
      }
    }
    if (!answersOnly) {
      if (setValue(solutionBox, result.solution, true)) {
        rememberForm(solutionBox, forms);
      }
    }
    return forms;
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

  function detailAnswersMissing() {
    var blocks = document.querySelectorAll('.subitem-block');
    if (blocks.length) {
      var missing = false;
      blocks.forEach(function (block) {
        var el = block.querySelector(
          '.subitem-edit-form textarea[name="answer_latex"]');
        if (!el || !el.value.trim()) missing = true;
      });
      return missing;
    }
    var answerBox = document.getElementById('qa_answer');
    return !answerBox || !answerBox.value.trim();
  }

  function formSubitemRows() {
    // extra=1 всегда даёт пустую строку; без фильтра задача без подпунктов
    // уходит в модель как один пустой, а ответ пишется не в основные поля.
    var rows = [];
    document.querySelectorAll(
      'table.formset[data-formset="subitems"] tr.formset-row'
    ).forEach(function (row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) return;
      var field = row.querySelector('textarea[name$="-text_latex"]');
      if (!field || field.name.indexOf('__prefix__') !== -1) return;
      if (!field.value.trim()) return;
      rows.push(row);
    });
    return rows;
  }

  function collectForm() {
    var textEl = document.getElementById('id_text_latex');
    var text = textEl ? textEl.value : '';
    var subitems = formSubitemRows().map(function (row) {
      return row.querySelector('textarea[name$="-text_latex"]').value;
    });
    return {text: text, subitems: subitems};
  }

  function fillForm(result, answersOnly) {
    var rows = formSubitemRows();
    if (rows.length) {
      rows.forEach(function (row, i) {
        var ansEl = row.querySelector('textarea[name$="-answer_latex"]');
        if (!answersOnly || (ansEl && !ansEl.value.trim())) {
          setValue(ansEl, (result.subitem_answers || [])[i], true);
        }
        if (!answersOnly) {
          setValue(row.querySelector('textarea[name$="-solution_latex"]'),
            (result.subitem_solutions || [])[i], true);
        }
      });
      return;
    }
    var answerBox = document.getElementById('id_answer_latex');
    if (!answersOnly || (answerBox && !answerBox.value.trim())) {
      setValue(answerBox, result.answer, true);
    }
    if (!answersOnly) {
      setValue(document.getElementById('id_solution_latex'), result.solution, true);
    }
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

  function formAnswersMissing() {
    var rows = formSubitemRows();
    if (rows.length) {
      var missing = false;
      rows.forEach(function (row) {
        var el = row.querySelector('textarea[name$="-answer_latex"]');
        if (!el || !el.value.trim()) missing = true;
      });
      return missing;
    }
    var answerBox = document.getElementById('id_answer_latex');
    return !answerBox || !answerBox.value.trim();
  }

  function payloadFor(el, collected) {
    var payload = {};
    if (collected) {
      payload.text = collected.text || '';
      payload.subitems = collected.subitems || [];
    }
    if (el.dataset.taskId) payload.task_id = el.dataset.taskId;
    return payload;
  }

  function worksheetTasks(extra) {
    extra = extra || '';
    var nodes = document.querySelectorAll(
      '#ws-items .ws-item[data-task-id]' + extra);
    var seen = {};
    var unique = [];
    Array.prototype.forEach.call(nodes, function (item) {
      var id = item.dataset.taskId;
      if (!id || seen[id]) return;
      seen[id] = true;
      unique.push(item);
    });
    return unique;
  }

  function runApplyQueue(el, items, extra) {
    extra = extra || {};
    var done = 0;
    var failed = 0;
    return withBusy(el, function () {
      return items.reduce(function (chain, item) {
        return chain.then(function () {
          el.textContent = 'Генерация ' + (done + 1) + '/' +
            items.length + '…';
          return solve({
            task_id: item.dataset.taskId,
            apply: true,
            overwrite: !!extra.overwrite,
            answers_only: !!extra.answersOnly,
          }).then(function () {
            done += 1;
          }).catch(function () {
            failed += 1;
          });
        });
      }, Promise.resolve());
    }).then(function () {
      if (failed) {
        toast(false, 'Не удалось: ' + failed + ' из ' + items.length);
      } else {
        toast(true, 'Черновики записаны — проверьте задачи');
      }
      window.location.reload();
    }).catch(function () {});
  }

  function onClick(ev) {
    var el = ev.target.closest('[data-neuro]');
    if (!el) return;
    ev.preventDefault();
    var kind = el.dataset.neuro;
    if (kind === 'task-detail' || kind === 'task-detail-answer') {
      var answersOnly = kind === 'task-detail-answer';
      if (answersOnly) {
        if (!detailAnswersMissing()) {
          toast(false, 'Ответ уже есть');
          return;
        }
      } else if (!confirmOverwrite(detailHasExisting())) {
        return;
      }
      withBusy(el, function () {
        return solve(payloadFor(el, collectDetail())).then(function (result) {
          return fillDetail(result, answersOnly);
        });
      }).then(function (forms) {
        var saved = saveFilledForms(forms || []);
        toast(true, saved
          ? 'Черновик сохранён — проверьте и поправьте'
          : 'Черновик в полях — сохраните, когда проверите');
      }).catch(function () {});
      return;
    }
    if (kind === 'task-form' || kind === 'task-form-answer') {
      var formAnswersOnly = kind === 'task-form-answer';
      if (formAnswersOnly) {
        if (!formAnswersMissing()) {
          toast(false, 'Ответ уже есть');
          return;
        }
      } else if (!confirmOverwrite(formHasExisting())) {
        return;
      }
      withBusy(el, function () {
        return solve(payloadFor(el, collectForm())).then(function (result) {
          fillForm(result, formAnswersOnly);
        });
      }).then(function () {
        toast(true, 'Черновик в полях — проверьте перед сохранением');
      }).catch(function () {});
      return;
    }
    if (kind === 'apply-answers') {
      var missing = worksheetTasks('[data-no-answer="1"]');
      if (!missing.length) {
        toast(false, 'Нет задач без ответа');
        return;
      }
      runApplyQueue(el, missing, {answersOnly: true});
      return;
    }
    if (kind === 'apply-all') {
      var all = worksheetTasks();
      if (!all.length) {
        toast(false, 'Нет задач в листке');
        return;
      }
      var hasExisting = all.some(function (item) {
        return item.dataset.hasAnswer === '1';
      });
      if (!confirmOverwrite(hasExisting)) return;
      runApplyQueue(el, all, {overwrite: hasExisting});
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
