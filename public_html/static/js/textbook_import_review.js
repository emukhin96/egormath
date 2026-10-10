(function () {
  'use strict';

  function wrapMathField(textarea) {
    var start = textarea.selectionStart;
    var end = textarea.selectionEnd;
    var value = textarea.value;
    if (start === end) {
      start = 0;
      end = value.length;
    }
    var selected = value.slice(start, end);
    var lead = (selected.match(/^\s*/) || [''])[0];
    var trail = (selected.match(/\s*$/) || [''])[0];
    var core = selected.slice(lead.length, selected.length - trail.length);
    if (!core) return;
    if (/^\$[\s\S]*\$$/.test(core) || /^\\\([\s\S]*\\\)$/.test(core)) return;
    var wrapped = lead + '$' + core + '$' + trail;
    textarea.value = value.slice(0, start) + wrapped + value.slice(end);
    textarea.focus();
    textarea.selectionStart = start + lead.length;
    textarea.selectionEnd = start + wrapped.length - trail.length;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll('.import-status-button'));
    var feedback = document.querySelector('.import-status-feedback');
    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        var radio = document.getElementById(button.dataset.radioId);
        if (!radio) return;
        radio.checked = true;
        buttons.forEach(function (other) {
          var active = other === button;
          other.classList.toggle('is-active', active);
          other.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (feedback) feedback.textContent = 'Выбрано: ' + button.textContent.trim();
      });
    });

    Array.prototype.slice.call(
      document.querySelectorAll('.import-wrap-math')).forEach(function (button) {
      button.addEventListener('click', function () {
        var field = document.getElementById(button.getAttribute('data-wrap-math'));
        if (field) wrapMathField(field);
      });
    });

    initMaskTools();
  });

  /* Маска в сверке: «Из ответа» — заготовка тем же кодом, что при загрузке;
     «Как увидит ученик» — поля ввода и ошибки разбора маски. */
  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function post(url, data) {
    var body = new URLSearchParams();
    Object.keys(data).forEach(function (key) { body.append(key, data[key]); });
    return fetch(url, {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (response) { return response.json(); });
  }

  function fieldValue(id) {
    var el = id && document.getElementById(id);
    return el ? el.value : '';
  }

  function showBox(box, html, errors) {
    box.hidden = false;
    box.innerHTML = '';
    if (errors && errors.length) {
      var list = document.createElement('ul');
      list.className = 'errorlist';
      errors.forEach(function (text) {
        var li = document.createElement('li');
        li.textContent = text;
        list.appendChild(li);
      });
      box.appendChild(list);
    }
    var holder = document.createElement('div');
    holder.innerHTML = html;
    box.appendChild(holder);
    if (typeof renderMathContent === 'function') {
      holder.querySelectorAll('.mask-text, .mask-order-items li, .math-content')
        .forEach(renderMathContent);
    }
    if (window.EgorMask && html) window.EgorMask.enhance(holder);
  }

  function initMaskTools() {
    var config = document.getElementById('import-mask-config');
    if (!config) return;
    document.querySelectorAll('.import-mask-tools').forEach(function (tools) {
      var mask = document.getElementById(tools.dataset.mask);
      var box = tools.parentNode.querySelector('[data-mask-preview-box]');
      if (!mask || !box) return;
      tools.querySelector('[data-import-mask-draft]').addEventListener('click', function () {
        var answer = fieldValue(tools.dataset.answer).trim()
          || fieldValue(tools.dataset.editorAnswer).trim();
        if (!answer) {
          showBox(box, '', ['Ответ пуст — заготовку делать не из чего.']);
          return;
        }
        var condition = (tools.dataset.condition || '').split(' ')
          .map(fieldValue).filter(Boolean).join('\n');
        post(config.dataset.draftUrl, {answer: answer, condition: condition}).then(function (res) {
          if (!res.ok) { showBox(box, '', [res.message || 'Тип ответа не определён — задайте маску вручную.']); return; }
          if (mask.value.trim() && mask.value.trim() !== res.mask
              && !window.confirm('Заменить текущую маску заготовкой?')) return;
          mask.value = res.mask;
          mask.dispatchEvent(new Event('input', {bubbles: true}));
          box.hidden = true;
        }).catch(function () { showBox(box, '', ['Не удалось сделать заготовку — попробуйте ещё раз.']); });
      });
      tools.querySelector('[data-import-mask-preview]').addEventListener('click', function () {
        if (!mask.value.trim()) {
          showBox(box, '', ['Маска пуста — ученик сможет прислать только фото решения.']);
          return;
        }
        post(config.dataset.previewUrl, {mask: mask.value, prefix: 'preview'}).then(function (res) {
          showBox(box, res.html || '', res.errors);
        }).catch(function () { showBox(box, '', ['Не удалось получить превью — попробуйте ещё раз.']); });
      });
    });
  }
})();
