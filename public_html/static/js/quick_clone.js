/* Диалог «Клон задачи»: кнопка с data-quick-clone="<url>" открывает
   <dialog> с фрагментом problems/_clone_dialog.html. Числа условия — поля
   .num-in; итоговый LaTeX собирается в textarea «…-text». Простая маска
   (числа эталонов = числа ответа) следует за ответом; сервер при сохранении
   пересчитывает её сам (problems/clone_numbers.py). Глобально:
   window.EgorClone.open(url). */
(function () {
  'use strict';

  // --- числа в LaTeX: порт problems/clone_numbers.find_numbers -------------
  var NUMBER_RE = /[0-9]+(?:(?:\.|\{,\}|,)[0-9]+)?/y;
  var UNIT_RE = /\s*(?:(?:pt|mm|cm|in|ex|em|bp|pc|dd|cc|sp|mu)(?![A-Za-z])|\\(?:textwidth|linewidth|columnwidth|textheight|paperwidth|hsize|vsize|baselineskip|parindent|fill)(?![A-Za-z]))/y;
  var SKIP_ARGS = {
    taskpic: 1, includegraphics: 1, vspace: 1, hspace: 1, label: 1, ref: 1,
    eqref: 1, pageref: 1, cite: 1, url: 1, href: 1, input: 1, include: 1,
    setlength: 2, addtolength: 2, setcounter: 2, addtocounter: 2, color: 1,
    textcolor: 1, colorbox: 1, cline: 1, multicolumn: 2, multirow: 2, rule: 2,
    parbox: 1, raisebox: 1, enlargethispage: 1
  };
  var OPTIONAL_ARGS = ['sqrt', 'makebox', 'framebox', 'parbox', 'raisebox',
    'includegraphics', 'item', 'rule', 'multirow', 'newline', 'linebreak', 'taskpic'];
  var ENV_ARGS = {tabular: 1, 'tabular*': 2, tabularx: 2, array: 1, longtable: 1,
    minipage: 1, multicols: 1, wrapfigure: 2};
  var SKIP_ENVS = ['tikzpicture', 'picture', 'pspicture'];

  function isLetter(ch) { return /^[A-Za-z]$/.test(ch || ''); }
  function isDigit(ch) { return /^[0-9]$/.test(ch || ''); }

  function skipGroup(text, i) {
    var depth = 0;
    while (i < text.length) {
      var ch = text[i];
      if (ch === '\\') { i += 2; continue; }
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) return i + 1; }
      i++;
    }
    return text.length;
  }

  function skipOptional(text, i) {
    i++;
    while (i < text.length) {
      var ch = text[i];
      if (ch === '\\') { i += 2; continue; }
      if (ch === '{') { i = skipGroup(text, i); continue; }
      if (ch === ']') return i + 1;
      i++;
    }
    return text.length;
  }

  function skipSpaces(text, i) {
    while (i < text.length && ' \t\r\n'.indexOf(text[i]) >= 0) i++;
    return i;
  }

  function skipArgs(text, i, count, optional) {
    for (;;) {
      if (optional && text[i] === '[') { i = skipOptional(text, i); continue; }
      if (count <= 0) return i;
      var j = skipSpaces(text, i);
      if (text[j] === '{') i = skipGroup(text, j);
      else if (j < text.length && '\\}'.indexOf(text[j]) < 0) i = j + 1;
      else return i;
      count--;
    }
  }

  function skipScript(text, i) {
    i = skipSpaces(text, i);
    if (i >= text.length) return i;
    if (text[i] === '{') return skipGroup(text, i);
    if (text[i] === '\\') {
      var j = i + 1;
      if (isLetter(text[j])) { while (isLetter(text[j])) j++; return j; }
      return j + 1;
    }
    return i + 1;
  }

  function findNumbers(text) {
    text = text || '';
    var found = [], n = text.length, i = 0, j, m, end;
    while (i < n) {
      var ch = text[i];
      if (ch === '%') { end = text.indexOf('\n', i); i = end < 0 ? n : end + 1; continue; }
      if (ch === '\\') {
        j = i + 1;
        if (isLetter(text[j])) {
          while (isLetter(text[j])) j++;
          var name = text.slice(i + 1, j);
          if (text[j] === '*') { j++; name += '*'; }
          var base = name.replace(/\*$/, '');
          if (base === 'begin') {
            var k = skipSpaces(text, j);
            if (text[k] === '{') {
              var close = skipGroup(text, k);
              var env = text.slice(k + 1, close - 1).trim();
              if (SKIP_ENVS.indexOf(env) >= 0) {
                end = text.indexOf('\\end{' + env + '}', close);
                i = end < 0 ? n : end;
                continue;
              }
              j = skipArgs(text, close, ENV_ARGS[env] || 0, true);
            }
          } else if (base === 'end') {
            j = skipArgs(text, j, 1, false);
          } else {
            j = skipArgs(text, j, SKIP_ARGS[base] || 0, OPTIONAL_ARGS.indexOf(base) >= 0);
          }
          i = j;
          continue;
        }
        j = Math.min(i + 2, n);
        if (text[i + 1] === '\\') {
          if (text[j] === '*') j++;
          if (text[j] === '[') j = skipOptional(text, j);
        }
        i = j;
        continue;
      }
      if (ch === '^' || ch === '_') { i = skipScript(text, i + 1); continue; }
      if (isDigit(ch)) {
        NUMBER_RE.lastIndex = i;
        m = NUMBER_RE.exec(text);
        end = NUMBER_RE.lastIndex;
        var lit = m[0];
        if (lit.indexOf(',') >= 0 && lit.indexOf('{,}') < 0 &&
            (/^,[0-9]/.test(text.slice(end, end + 2)) ||
             (i >= 2 && text[i - 1] === ',' && isDigit(text[i - 2])))) {
          end = i + lit.indexOf(',');
        }
        UNIT_RE.lastIndex = end;
        if (!UNIT_RE.exec(text)) found.push({start: i, end: end, value: text.slice(i, end)});
        i = end;
        continue;
      }
      i++;
    }
    return found;
  }

  // Минус перед числом (как clone_numbers.is_negative): знак у маски «за
  // ответом» должен совпадать, иначе маску правят вручную.
  function isNegative(text, start) {
    var i = start - 1;
    while (i >= 0 && ' \t\r\n'.indexOf(text[i]) >= 0) i--;
    return i >= 0 && (text[i] === '-' || text[i] === '\u2212');
  }

  function signedNumbers(text) {
    return findNumbers(text).map(function (n) {
      n.negative = isNegative(text || '', n.start);
      return n;
    });
  }

  // --- вид исходного LaTeX в поле условия (только показ) -------------------
  var PRETTY = [
    [/\\(?:displaystyle|textstyle|left|right|bigl|bigr|Bigl|Bigr)(?![A-Za-z])\s*/g, ''],
    [/\\[()[\]]|\$/g, ''],
    [/\^\{?\\circ\}?/g, '°'],
    [/\\cdot(?![A-Za-z])\s*/g, '·'], [/\\times(?![A-Za-z])\s*/g, '×'],
    [/\\leqslant(?![A-Za-z])\s*|\\leq?(?![A-Za-z])\s*/g, '≤'],
    [/\\geqslant(?![A-Za-z])\s*|\\geq?(?![A-Za-z])\s*/g, '≥'],
    [/\\neq?(?![A-Za-z])\s*/g, '≠'], [/\\pi(?![A-Za-z])\s*/g, 'π'],
    [/\\alpha(?![A-Za-z])\s*/g, 'α'], [/\\beta(?![A-Za-z])\s*/g, 'β'],
    [/\\sqrt(?![A-Za-z])\s*/g, '√'], [/\\operatorname\{(\w+)\}/g, '$1'],
    [/\\(sin|cos|tg|ctg|log|lg|ln)(?![A-Za-z])/g, '$1'],
    [/\{,\}/g, ','], [/~/g, ' ']
  ];

  function pretty(tex) {
    PRETTY.forEach(function (rule) { tex = tex.replace(rule[0], rule[1]); });
    return tex;
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }

  // --- диалог ----------------------------------------------------------------
  var dialog = null;
  // after — строка листка, после которой встанет следующий клон
  var state = {url: '', dirty: false, reload: false, saved: '', after: null, count: 0};
  var TOAST_KEY = 'egorCloneToast';
  var previewTimer = null;
  var toastTimer = null;

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.className = 'qclone-dialog';
    dialog.setAttribute('aria-labelledby', 'qclone-title');
    document.body.appendChild(dialog);
    dialog.addEventListener('close', function () {
      dialog.innerHTML = '';
      if (state.dirty && state.reload) reloadWithToast();
    });
    dialog.addEventListener('click', function (e) {
      if (e.target.closest('[data-qclone-close]')) dialog.close();
    });
    return dialog;
  }

  // Тост переживает перезагрузку страницы (листок, самостоятельная)
  function reloadWithToast() {
    var message = state.count > 1 ? 'Сохранено клонов: ' + state.count : state.lastMessage;
    try { window.sessionStorage.setItem(TOAST_KEY, message || ''); } catch (e) { /* без тоста */ }
    window.location.reload();
  }

  function toast(ok, message, url) {
    var badge = document.getElementById('ws-saved');
    if (!badge) return;
    badge.textContent = message;
    if (url) {
      var link = document.createElement('a');
      link.href = url;
      link.textContent = 'открыть';
      badge.appendChild(document.createTextNode(' · '));
      badge.appendChild(link);
    }
    badge.classList.toggle('ws-saved-error', !ok);
    badge.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { badge.hidden = true; }, url ? 6000 : 4000);
  }

  function load() {
    return fetch(state.url, {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'})
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.text();
      })
      .then(function (html) {
        dialog.innerHTML = html;
        var form = dialog.querySelector('form.qclone');
        if (form) init(form);
        if (!dialog.open) dialog.showModal();
        var first = dialog.querySelector('.num-in, input[data-answer], .btn');
        if (first) first.focus();
      });
  }

  function open(url) {
    ensureDialog();
    state = {url: url, dirty: false, reload: false, saved: '', after: null, count: 0};
    load().catch(function () { toast(false, 'Не удалось открыть клон задачи'); });
  }

  function owners(form) { return Array.prototype.slice.call(form.querySelectorAll('[data-owner]')); }

  function fitInput(input) {
    input.style.width = Math.max(2, input.value.length + 1) + 'ch';
  }

  // Текст условия из полей чисел (или textarea, если правят целиком)
  function syncText(owner) {
    var raw = owner.querySelector('.qclone-raw');
    if (owner.dataset.rawMode === '1') return raw.value;
    var parts = [];
    owner.querySelectorAll('[data-stmt] > *').forEach(function (node) {
      parts.push(node.tagName === 'INPUT' ? node.value : node.dataset.raw);
    });
    raw.value = parts.join('');
    return raw.value;
  }

  function substituteSlots(mask, slots, numbers) {
    var out = '', pos = 0;
    slots.forEach(function (slot, i) {
      out += mask.slice(pos, slot[0]) + numbers[i].value.replace('{,}', ',');
      pos = slot[1];
    });
    return out + mask.slice(pos);
  }

  function updateMask(owner) {
    var field = owner.querySelector('[data-mask-field]');
    var answer = owner.querySelector('[data-answer]');
    if (!field || !answer) return;
    var textarea = field.querySelector('textarea');
    var follow = field.querySelector('[data-mask-follow]');
    var view = field.querySelector('[data-mask-view]');
    var check = field.querySelector('[data-mask-check]');
    var changed = answer.value.trim() !== answer.defaultValue.trim();
    var was = owner.querySelector('[data-answer-was]');
    if (was) was.hidden = !changed;
    if (field.dataset.follows === '1' && field.dataset.manual !== '1') {
      var slots = JSON.parse(field.dataset.maskSlots || '[]');
      var numbers = signedNumbers(answer.value);
      var old = signedNumbers(answer.defaultValue);
      var signChanged = numbers.some(function (n, i) { return old[i] && old[i].negative !== n.negative; });
      if (numbers.length === slots.length && !signChanged) {
        var mask = substituteSlots(textarea.defaultValue, slots, numbers);
        textarea.value = mask;
        view.querySelector('[data-mask-text]').textContent = mask;
        view.hidden = false;
        textarea.hidden = true;
        follow.value = '1';
        check.hidden = true;
        return;
      }
      follow.value = '0';
      view.hidden = true;
      textarea.hidden = false;
      textarea.value = textarea.defaultValue;
      check.textContent = signChanged && numbers.length === slots.length
        ? 'Проверьте маску: у числа в ответе сменился знак.'
        : 'Проверьте маску: в новом ответе другое количество чисел.';
      check.hidden = false;
      return;
    }
    if (field.dataset.follows !== '1' && textarea.defaultValue.trim()) {
      check.textContent = 'Проверьте маску: она не обновляется по ответу.';
      check.hidden = !changed || field.dataset.manual === '1';
    }
  }

  function diffHtml(form) {
    var rows = [];
    owners(form).forEach(function (owner) {
      var title = owner.dataset.title;
      var html = '', changed = false;
      if (owner.dataset.rawMode === '1') {
        var raw = owner.querySelector('.qclone-raw');
        if (raw.value !== raw.defaultValue) {
          changed = true;
          html = '<i>текст правится целиком — сверьте в «Ученик увидит»</i>';
        }
      } else {
        owner.querySelectorAll('[data-stmt] > *').forEach(function (node) {
          if (node.tagName !== 'INPUT') { html += escapeHtml(pretty(node.dataset.raw)); return; }
          if (node.value !== node.dataset.orig) {
            changed = true;
            html += '<del>' + escapeHtml(node.dataset.orig) + '</del><ins>' + escapeHtml(node.value) + '</ins>';
          } else {
            html += escapeHtml(node.value);
          }
        });
      }
      var answer = owner.querySelector('[data-answer]');
      var answerHtml = '';
      if (answer && answer.value.trim() !== answer.defaultValue.trim()) {
        answerHtml = '<div class="qclone-diff-answer">Ответ: <del>' + escapeHtml(answer.defaultValue || '—') +
          '</del> <ins>' + escapeHtml(answer.value || '—') + '</ins></div>';
      }
      if (changed || answerHtml) {
        rows.push('<div class="qclone-diff-row"><b>' + escapeHtml(title) + '.</b> ' +
          (changed ? html : '<span class="qclone-hint">без изменений</span>') + answerHtml + '</div>');
      }
    });
    return rows.length ? rows.join('') : '<span class="qclone-hint">Пока ничего не изменено.</span>';
  }

  function schedulePreview(form) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(function () { renderPreview(form); }, 350);
  }

  function renderPreview(form) {
    var box = form.querySelector('[data-student]');
    var body = new FormData();
    body.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
    owners(form).forEach(function (owner) {
      body.append(owner.dataset.owner === 'task' ? 'text' : 'sub', syncText(owner));
    });
    fetch(form.dataset.previewUrl, {method: 'POST', body: body, credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!form.isConnected) return;
        box.innerHTML = data.html;
        renderMath(box);
      })
      .catch(function () {});
  }

  function renderMath(box) {
    if (typeof window.renderMathContent !== 'function') return;
    box.querySelectorAll('.math-content').forEach(window.renderMathContent);
  }

  function refresh(form) {
    owners(form).forEach(function (owner) { syncText(owner); updateMask(owner); });
    form.querySelector('[data-diff]').innerHTML = diffHtml(form);
  }

  function showErrors(form, errors) {
    var box = form.querySelector('[data-qclone-errors]');
    box.textContent = (errors || ['Не удалось сохранить клон']).join(' ');
    box.hidden = false;
    box.scrollIntoView({block: 'nearest'});
  }

  function save(form, again) {
    refresh(form);
    var buttons = form.querySelectorAll('.qclone-foot .btn');
    buttons.forEach(function (b) { b.disabled = true; });
    fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) {
        return r.json().catch(function () { return {ok: false, errors: ['Ошибка сервера (' + r.status + ')']}; });
      })
      .then(function (data) {
        if (!data.ok) {
          buttons.forEach(function (b) { b.disabled = false; });
          showErrors(form, data.errors);
          return;
        }
        state.dirty = true;
        state.reload = !!data.reload;
        state.count += 1;
        state.lastMessage = data.message;
        if (again) {
          if (data.item_id) state.after = data.item_id;
          state.saved = data.message + ' ✓ Можно делать следующий.';
          return load();
        }
        if (data.reload) {
          state.dirty = false;
          reloadWithToast();
          return;
        }
        dialog.close();
        toast(true, data.message, data.url);
      })
      .catch(function () {
        buttons.forEach(function (b) { b.disabled = false; });
        showErrors(form, ['Нет связи — клон не сохранён']);
      });
  }

  function focusNext(input) {
    var inputs = Array.prototype.slice.call(dialog.querySelectorAll('.num-in'))
      .filter(function (el) { return el.offsetParent !== null; });
    var next = inputs[inputs.indexOf(input) + 1];
    if (next) { next.focus(); next.select(); }
  }

  function init(form) {
    form.querySelectorAll('.qclone-tex').forEach(function (span) {
      span.textContent = pretty(span.dataset.raw);
    });
    form.querySelectorAll('.num-in').forEach(fitInput);
    if (state.after && form.querySelector('[name=item]')) {
      var after = document.createElement('input');
      after.type = 'hidden';
      after.name = 'after';
      after.value = state.after;
      form.appendChild(after);
    }
    if (state.saved) {
      var note = form.querySelector('[data-qclone-note]');
      note.textContent = state.saved;
      note.classList.add('is-saved');
    }
    form.addEventListener('input', function (e) {
      var target = e.target;
      if (target.classList.contains('num-in')) {
        fitInput(target);
        target.classList.toggle('is-changed', target.value !== target.dataset.orig);
      }
      if (target.matches('[data-mask-field] textarea')) {
        var field = target.closest('[data-mask-field]');
        field.dataset.manual = '1';
        field.querySelector('[data-mask-follow]').value = '0';
        field.querySelector('[data-mask-check]').hidden = true;
      }
      refresh(form);
      if (target.classList.contains('num-in') || target.classList.contains('qclone-raw')) schedulePreview(form);
    });
    form.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target.matches('.num-in, input[data-answer]')) {
        e.preventDefault();
        if (e.target.classList.contains('num-in')) focusNext(e.target);
      }
    });
    form.addEventListener('change', function (e) {
      var radio = e.target;
      if (radio.type !== 'radio' || !radio.closest('[data-pic]')) return;
      var pic = radio.closest('[data-pic]');
      var file = pic.querySelector('[data-pic-file]');
      file.hidden = radio.value !== 'replace';
      if (radio.value === 'replace') file.click();
      var warn = pic.querySelector('[data-pic-warn]');
      if (warn) warn.hidden = radio.value !== 'remove';
      pic.classList.toggle('is-removed', radio.value === 'remove');
    });
    form.addEventListener('click', function (e) {
      var toggle = e.target.closest('[data-raw-toggle]');
      if (toggle) {
        var owner = toggle.closest('[data-owner]');
        syncText(owner);
        owner.dataset.rawMode = '1';
        owner.querySelector('[data-stmt]').hidden = true;
        var raw = owner.querySelector('.qclone-raw');
        raw.hidden = false;
        raw.focus();
        toggle.hidden = true;
        return;
      }
      var edit = e.target.closest('[data-mask-edit]');
      if (edit) {
        var field = edit.closest('[data-mask-field]');
        field.dataset.manual = '1';
        field.querySelector('[data-mask-follow]').value = '0';
        field.querySelector('[data-mask-view]').hidden = true;
        var textarea = field.querySelector('textarea');
        textarea.hidden = false;
        textarea.focus();
        return;
      }
      if (e.target.closest('[data-qclone-again]')) save(form, true);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      save(form, false);
    });
    refresh(form);
    renderMath(form.querySelector('[data-student]'));
  }

  document.addEventListener('DOMContentLoaded', function () {
    var message = null;
    try {
      message = window.sessionStorage.getItem(TOAST_KEY);
      window.sessionStorage.removeItem(TOAST_KEY);
    } catch (e) { /* хранилище недоступно */ }
    if (message) toast(true, message);
  });

  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-quick-clone]');
    if (!button) return;
    e.preventDefault();
    open(button.dataset.quickClone);
  });

  window.EgorClone = {open: open, findNumbers: findNumbers, signedNumbers: signedNumbers};
})();
