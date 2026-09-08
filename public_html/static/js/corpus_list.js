/* Пропуск черновика или задачи корпуса без перезагрузки. */
(function () {
  'use strict';

  var pending = new WeakMap();
  var generation = new WeakMap();

  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) {
      EgorAutosave.showSaved(ok, message);
    }
  }

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el && el.value) return el.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function statusFilter() {
    var sel = document.querySelector('select[name="status"]');
    return sel ? sel.value : '';
  }

  function applyRow(row, skipped, statusLabel) {
    if (!row) return;
    row.classList.toggle('is-skipped', skipped);
    row.dataset.status = skipped ? 'skipped' : 'needs_review';
    var statusCell = row.querySelector('.corpus-row-status');
    if (statusCell && statusLabel) statusCell.textContent = statusLabel;
    var filter = statusFilter();
    var status = skipped ? 'skipped' : 'needs_review';
    if (filter === '') {
      row.hidden = skipped;
    } else {
      row.hidden = filter !== status;
    }
  }

  function updateCounts(counts) {
    if (!counts) return;
    Object.keys(counts).forEach(function (key) {
      var el = document.querySelector('[data-corpus-count="' + key + '"]');
      if (el) el.textContent = counts[key];
    });
  }

  function postSkip(key, url, skip, extra) {
    var gen = (generation.get(key) || 0) + 1;
    generation.set(key, gen);
    var body = extra && extra.body ? extra.body : new FormData();
    if (!(body instanceof FormData)) body = new FormData();
    body.set('skip', skip);
    if (extra && extra.index != null && extra.index !== '') {
      body.set('index', extra.index);
    }
    if (!body.has('csrfmiddlewaretoken')) {
      body.set('csrfmiddlewaretoken', csrfToken());
    }
    var run = (pending.get(key) || Promise.resolve()).then(function () {
      return fetch(url, {
        method: 'POST',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        body: body,
      }).then(function (resp) {
        return resp.json().then(function (data) {
          return {httpOk: resp.ok, data: data};
        }).catch(function () {
          return {httpOk: false, data: {ok: false, message: 'Ошибка сохранения'}};
        });
      });
    }).then(function (result) {
      if (generation.get(key) !== gen) return result;
      if (extra && extra.onDone) extra.onDone(result);
      return result;
    }).catch(function () {
      if (generation.get(key) !== gen) return;
      if (extra && extra.onFail) extra.onFail();
    });
    pending.set(key, run);
    return run;
  }

  function sendFormSkip(form, skip, checkbox) {
    var body = new FormData(form);
    var row = form.closest('tr');
    applyRow(row, skip === '1', skip === '1' ? 'пропущена' : 'не проверена');
    postSkip(form, form.getAttribute('action') || form.action, skip, {
      body: body,
      onDone: function (result) {
        var data = result.data || {};
        if (!result.httpOk || !data.ok) {
          checkbox.checked = skip !== '1';
          applyRow(row, checkbox.checked,
                   checkbox.checked ? 'пропущена' : 'не проверена');
          toast(false, data.message || 'Не удалось сохранить');
          return;
        }
        checkbox.checked = !!data.skipped;
        applyRow(row, data.skipped, data.status_label);
        updateCounts(data.counts);
        toast(true, data.skipped ? 'Пропущен' : 'На проверке');
      },
      onFail: function () {
        checkbox.checked = skip !== '1';
        applyRow(row, checkbox.checked,
                 checkbox.checked ? 'пропущена' : 'не проверена');
        toast(false, 'Нет связи — изменение не сохранено');
      },
    });
  }

  function sendBoxSkip(checkbox, skip, apply, okMessage, failRevert) {
    var url = checkbox.getAttribute('data-url');
    if (!url) return;
    apply(skip === '1');
    postSkip(checkbox, url, skip, {
      index: checkbox.getAttribute('data-index'),
      onDone: function (result) {
        var data = result.data || {};
        if (!result.httpOk || !data.ok) {
          checkbox.checked = failRevert(skip);
          apply(checkbox.checked);
          toast(false, data.message || 'Не удалось сохранить');
          return;
        }
        checkbox.checked = !!data.skipped;
        apply(!!data.skipped, data);
        toast(true, okMessage(!!data.skipped));
      },
      onFail: function () {
        checkbox.checked = failRevert(skip);
        apply(checkbox.checked);
        toast(false, 'Нет связи — изменение не сохранено');
      },
    });
  }

  document.addEventListener('change', function (e) {
    var checkbox = e.target;
    if (!checkbox || checkbox.type !== 'checkbox') return;
    var form = checkbox.closest('form.corpus-skip-form');
    if (form) {
      sendFormSkip(form, checkbox.checked ? '1' : '0', checkbox);
      return;
    }
    if (checkbox.classList.contains('corpus-task-skip')) {
      var row = checkbox.closest('tr');
      sendBoxSkip(
        checkbox, checkbox.checked ? '1' : '0',
        function (skipped) {
          if (row) row.classList.toggle('import-skipped', skipped);
        },
        function (skipped) { return skipped ? 'Задача пропущена' : 'Задача на проверке'; },
        function (skip) { return skip !== '1'; });
      return;
    }
    if (checkbox.classList.contains('corpus-draft-skip')) {
      sendBoxSkip(
        checkbox, checkbox.checked ? '1' : '0',
        function (skipped, data) {
          var status = document.querySelector('[data-corpus-draft-status]');
          if (status) {
            status.textContent = (data && data.status_label)
              ? data.status_label
              : (skipped ? 'пропущена' : 'не проверена');
          }
        },
        function (skipped) { return skipped ? 'Пропущен' : 'На проверке'; },
        function (skip) { return skip !== '1'; });
    }
  });

  document.addEventListener('submit', function (e) {
    if (e.target && e.target.classList.contains('corpus-skip-form')) {
      e.preventDefault();
    }
  });

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function syncExamParents(changed) {
    var group = changed && changed.closest('[data-exam-group]');
    var groups = group
      ? [group]
      : Array.prototype.slice.call(document.querySelectorAll('[data-exam-group]'));
    groups.forEach(function (el) {
      var line = el.querySelector('[data-exam-line]');
      var children = el.querySelectorAll('[data-exam-child]');
      var anyChild = false;
      children.forEach(function (c) {
        if (c.checked) anyChild = true;
      });
      if (changed && changed.hasAttribute('data-exam-line') && !changed.checked) {
        children.forEach(function (c) { c.checked = false; });
        return;
      }
      if (anyChild && line) line.checked = true;
    });
  }

  function refreshExamChips() {
    var box = document.querySelector('[data-corpus-exam-chips]');
    if (!box) return;
    var html = [];
    document.querySelectorAll(
        '.corpus-exam-fieldset input[name="exam_item_codes"]:checked'
    ).forEach(function (input) {
      var label = input.closest('label');
      var text = label ? label.textContent.trim() : input.value;
      text = text.replace(/^только\s+/, '');
      html.push('<span class="corpus-exam-chip">' + escapeHtml(text) + '</span>');
    });
    box.innerHTML = html.join('');
  }

  document.addEventListener('change', function (e) {
    if (e.target && e.target.name === 'exam_item_codes') {
      syncExamParents(e.target);
      refreshExamChips();
    }
  });

  syncExamParents();
  refreshExamChips();

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || !form.classList.contains('corpus-push-form')) return;
    e.preventDefault();
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    var body = new FormData(form);
    fetch(form.getAttribute('action') || '', {
      method: 'POST',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      body: body,
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return {httpOk: resp.ok, data: data};
      }).catch(function () {
        return {httpOk: false, data: {ok: false, message: 'Ошибка сохранения'}};
      });
    }).then(function (result) {
      var data = result.data || {};
      if (!result.httpOk || !data.ok) {
        if (btn) btn.disabled = false;
        toast(false, data.message || 'Не удалось загрузить');
        return;
      }
      toast(true, data.message || 'Загружено в каталог');
      updateCounts(data.counts);
      var row = form.closest('tr');
      if (row) {
        row.dataset.status = data.status || 'imported';
        var statusCell = row.querySelector('.corpus-row-status');
        if (statusCell && data.status_label) {
          statusCell.textContent = data.status_label;
        }
      }
      var skipForm = row && row.querySelector('.corpus-skip-form');
      if (skipForm) skipForm.remove();
      var cell = form.closest('td');
      if (cell) {
        cell.innerHTML = '<span class="muted">в каталоге</span>';
      }
    }).catch(function () {
      if (btn) btn.disabled = false;
      toast(false, 'Нет связи — изменение не сохранено');
    });
  });
})();
