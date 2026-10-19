/* Маска ответа в форме задачи.

   1. Превью «как увидит ученик»: при вводе в любое поле маски
      (textarea[data-mask-source] — у задачи и в строках подпунктов) сервер
      разбирает маску и возвращает разметку с контролами ученика + ошибки.
   2. Самопроверка: учитель заполняет превью пробным ответом и нажимает
      «Проверить пробный ответ» — результат по слотам считает тот же код,
      что и у ученика (эндпоинт task_mask_check, он же у «Проверить как
      ученик» на карточке задачи).
   3. «Заготовка из ответа»: из текстового «Ответа» сервер делает черновик
      маски для очевидных случаев (число, промежуток, пары, уравнение…). */
(function () {
  'use strict';

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function post(url, data) {
    var body = new URLSearchParams();
    Object.keys(data).forEach(function (k) { body.append(k, data[k]); });
    return fetch(url, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (r) { return r.json(); });
  }

  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) EgorAutosave.showSaved(ok, message);
    else if (!ok) window.alert(message);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('task-form');
    var panel = document.getElementById('mask-preview');
    if (!form || !panel) return;
    var previewUrl = panel.dataset.previewUrl;
    var checkUrl = panel.dataset.checkUrl;
    var draftUrl = panel.dataset.draftUrl;
    var container = panel.querySelector('[data-mask-html]');
    var errors = panel.querySelector('[data-mask-errors]');
    var title = panel.querySelector('[data-mask-title]');
    var result = panel.querySelector('[data-mask-result]');
    var active = null;
    var timer = null;
    var previewSeq = 0;

    function sourceLabel(textarea) {
      if (textarea.dataset.maskSource === 'task') return 'Превью: маска задачи';
      var row = textarea.closest('tr');
      var order = row && row.querySelector('input[name$="-order"]');
      return 'Превью: подпункт' + (order && order.value ? ' ' + order.value : '');
    }

    function showErrors(list) {
      errors.textContent = '';
      (list || []).forEach(function (text) {
        var li = document.createElement('li');
        li.textContent = text;
        errors.appendChild(li);
      });
      errors.hidden = !list || !list.length;
    }

    /* Пробные значения из превью: обычные поля по имени, math-field — по
       имени зеркального скрытого input */
    function collectValues() {
      var data = {};
      container.querySelectorAll('input[name], select[name]').forEach(function (el) {
        if (el.type === 'hidden') return;
        if (el.type === 'checkbox') { if (el.checked) data[el.name] = el.value; return; }
        data[el.name] = el.value;
      });
      container.querySelectorAll('math-field[data-mirror]').forEach(function (mf) {
        data[mf.dataset.mirror] = (window.EgorMask && EgorMask.value)
          ? EgorMask.value(mf) : (mf.value || '');
      });
      return data;
    }

    function preview(textarea, withValues) {
      active = textarea;
      title.textContent = sourceLabel(textarea);
      var data = withValues ? collectValues() : {};
      data.mask = textarea.value;
      panel.hidden = false;
      result.textContent = '';
      var seq = ++previewSeq;
      post(withValues ? checkUrl : previewUrl, data).then(function (res) {
        if (seq !== previewSeq || active !== textarea) return;
        showErrors(res.errors);
        if (!withValues) {
          container.innerHTML = res.html || '';
          if (typeof renderMathContent === 'function') {
            container.querySelectorAll('.mask-text, .mask-order-items li').forEach(renderMathContent);
          }
          /* Те же виджеты, что у ученика: числовая прямая, перетаскивание */
          if (res.html && window.EgorMask) EgorMask.enhance(container);
          if (!res.html) {
            container.innerHTML = '<span class="muted">' +
              (textarea.value.trim() ? 'Маска не разобрана' : 'Маска пуста — ученик сможет прислать только фото') +
              '</span>';
          }
          return;
        }
        if (window.EgorCheckBadge) EgorCheckBadge.apply(container, res.checks || {});
        /* Итог по задаче — в checks под префиксом полей (как у ученика) */
        var overall = (res.checks || {}).preview || '';
        result.textContent = overall === 'ok' ? 'Итог: верно'
          : overall === 'wrong' ? 'Итог: неверно'
          : overall === 'unknown' ? 'Итог: не разобрано (или не все слоты заполнены)'
          : (res.message || 'Введите пробный ответ в поля превью');
      }).catch(function () {
        showErrors(['Не удалось получить превью — попробуйте ещё раз']);
      });
    }

    function schedule(textarea) {
      clearTimeout(timer);
      previewSeq += 1;
      timer = setTimeout(function () { preview(textarea, false); }, 400);
    }

    form.addEventListener('input', function (e) {
      if (e.target.matches('textarea[data-mask-source]')) schedule(e.target);
    });
    form.addEventListener('focusin', function (e) {
      if (e.target.matches('textarea[data-mask-source]') && e.target !== active) {
        if (e.target.value.trim()) {
          clearTimeout(timer);
          preview(e.target, false);
        } else {
          active = e.target;
          previewSeq += 1;
          title.textContent = sourceLabel(e.target);
        }
      }
    });

    var checkBtn = panel.querySelector('[data-mask-check]');
    if (checkBtn) {
      checkBtn.addEventListener('click', function () {
        if (active) preview(active, true);
        else toast(false, 'Сначала введите маску');
      });
    }

    /* Заготовка из «Ответа»: у задачи — поле answer_latex формы,
       у подпункта — поле ответа той же строки */
    form.addEventListener('click', function (e) {
      var preset = e.target.closest('[data-mask-template]');
      if (preset) {
        var field = preset.closest('.problem-section').querySelector('textarea[data-mask-source]');
        var snippet = '{{' + (preset.dataset.maskKind || 'number') + ': ' + preset.dataset.maskTemplate + '}}';
        field.setRangeText(snippet, field.selectionStart, field.selectionEnd, 'select');
        field.dispatchEvent(new Event('input', {bubbles: true})); field.focus(); return;
      }
      var btn = e.target.closest('[data-mask-draft]');
      if (!btn) return;
      var row = btn.closest('tr');
      var scope = row || form;
      var textarea = scope.querySelector(row ? 'textarea[data-mask-source]' : 'textarea[data-mask-source=task]');
      var answer = row ? row.querySelector('textarea[name$="-answer_latex"]')
        : form.querySelector('textarea[name="answer_latex"]');
      var author = row ? row.querySelector('textarea[name$="-author_answer_latex"]') : form.querySelector('textarea[name="author_answer_latex"]');
      if (author && author.value.trim()) answer = author;
      if (!textarea || !answer) return;
      if (!answer.value.trim()) { toast(false, 'Поле «Ответ» пустое — заготовку делать не из чего'); return; }
      post(draftUrl, {answer: answer.value, condition: (form.querySelector('[name=text_latex]')?.value || '') + (row ? '\n' + (row.querySelector('[name$="-text_latex"]')?.value || '') : '')}).then(function (res) {
        if (!res.ok) { toast(false, res.message || 'Не удалось сделать заготовку'); return; }
        if (textarea.value.trim() && !window.confirm('Заменить текущую маску заготовкой?')) return;
        textarea.value = res.mask;
        textarea.dispatchEvent(new Event('input', {bubbles: true}));
        textarea.focus();
      }).catch(function () { toast(false, 'Не удалось сделать заготовку'); });
    });

    /* Есть сохранённая маска задачи — сразу показать превью */
    var first = form.querySelector('textarea[data-mask-source="task"]');
    if (first && first.value.trim()) preview(first, false);
  });
})();
