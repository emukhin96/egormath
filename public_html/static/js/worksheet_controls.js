/* Действия конструктора без навигации и выбор номеров для получателя. */
(function () {
  'use strict';
  var list = document.getElementById('ws-items');
  if (!list) return;
  var dialog = document.getElementById('recipient-visibility-dialog');
  var busy = false;
  var recipientHistory = [];
  dialog.addEventListener('close', function () { recipientHistory = []; });

  async function page(url) {
    var response = await fetch(url, {credentials: 'same-origin'});
    if (!response.ok || response.redirected) throw new Error('Не удалось загрузить данные. Повторите попытку.');
    return new DOMParser().parseFromString(await response.text(), 'text/html');
  }

  async function refresh() {
    var doc = await page(location.href), freshList = doc.getElementById('ws-items');
    if (!freshList) throw new Error('Не удалось обновить листок');
    var freshRows = Array.from(freshList.children);
    var ids = new Set(freshRows.map(function (row) { return row.dataset.id; }));
    Array.from(list.children).forEach(function (row) { if (!ids.has(row.dataset.id)) row.remove(); });
    freshRows.forEach(function (fresh) {
      var row = list.querySelector('.ws-item[data-id="' + fresh.dataset.id + '"]');
      if (!row) {
        row = fresh;
        row.querySelectorAll('.math-content').forEach(renderMathContent);
      } else {
        // Сохраняем DOM полей и черновики текста в оставшихся строках.
        var number = row.querySelector('.ws-num'), nextNumber = fresh.querySelector('.ws-num');
        if (number && nextNumber) number.textContent = nextNumber.textContent;
        var actions = row.querySelector('.ws-actions');
        if (actions) actions.replaceWith(fresh.querySelector('.ws-actions'));
        var visibility = row.querySelector('dialog');
        if (visibility) visibility.replaceWith(fresh.querySelector('dialog'));
      }
      list.appendChild(row);
    });
    document.getElementById('ws-undo').innerHTML = doc.getElementById('ws-undo').innerHTML;
    document.getElementById('ws-empty').hidden = freshRows.length > 0;
    document.querySelectorAll('[data-worksheet-item-count]').forEach(function (count) { count.textContent = freshRows.length; });
    document.querySelectorAll('[data-progress-cell^="status-"]').forEach(function (cell) {
      var fresh = doc.querySelector('[data-progress-cell="' + cell.dataset.progressCell + '"]');
      if (fresh) cell.innerHTML = fresh.innerHTML;
    });
    document.querySelectorAll('dialog[id^="assignment-status-"]').forEach(function (modal) {
      var fresh = doc.getElementById(modal.id);
      if (fresh && !modal.open) modal.replaceWith(fresh);
    });
    var recipients = document.getElementById('worksheet-recipients');
    if (recipients && doc.getElementById(recipients.id)) recipients.replaceWith(doc.getElementById(recipients.id));
    document.dispatchEvent(new CustomEvent('worksheet:updated'));
  }

  document.addEventListener('keydown', function (e) {
    if (e.target.matches('td[data-dialog-open]') && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault(); e.target.click();
    }
  });
  document.addEventListener('change', function (e) {
    if (e.target.matches('[data-photo-toggle]')) {
      e.target.form.elements.allow_photos.value = e.target.checked ? 'yes' : 'no';
      e.target.form.querySelector('[data-photo-mixed]').hidden = true;
    }
    if (e.target.matches('[name=due_action]')) {
      e.target.form.elements.due_at.disabled = e.target.value !== 'set';
    }
    if (!e.target.matches('[name=visible_items]')) return;
    var preserved = e.target.form.querySelector('[name=unchanged_items][value="' + e.target.value + '"]');
    if (preserved) preserved.remove();
  });
  document.addEventListener('click', async function (e) {
    if (e.target.closest('[data-recipient-back]')) {
      if (!busy && recipientHistory.length) {
        dialog.replaceChildren(recipientHistory.pop());
        dialog.querySelector('[data-recipient-back]').focus();
      }
      return;
    }
    var share = e.target.closest('.ws-share-link');
    if (share && e.target.closest('[data-share-copy]')) {
      try {
        await navigator.clipboard.writeText(share.querySelector('.ws-share-url').href);
        window.EgorAutosave.showSaved(true, 'Ссылка скопирована');
      } catch (error) { window.EgorAutosave.showSaved(false, 'Не удалось скопировать ссылку'); }
    }
    if (share && e.target.closest('[data-share-edit]')) {
      var editor = share.querySelector('[data-share-comment]');
      editor.hidden = false; editor.elements.comment.focus();
    }
    if (share && e.target.closest('[data-share-cancel]')) {
      var editor = share.querySelector('[data-share-comment]');
      editor.reset(); editor.hidden = true;
    }
    var dismiss = e.target.closest('[data-undo-dismiss]');
    if (dismiss) dismiss.closest('.undo-bar').hidden = true;
    var select = e.target.closest('[data-visibility-select]');
    if (select) {
      select.form.querySelectorAll('[name=visible_items]').forEach(function (input) {
        input.checked = select.dataset.visibilitySelect === 'all';
        input.indeterminate = false;
      });
    }
    if (select) select.form.querySelectorAll('[name=unchanged_items]').forEach(function (input) { input.remove(); });
    var button = e.target.closest('[data-visibility-url]');
    if (!button || busy) return;
    busy = true;
    button.disabled = true;
    try {
      var doc = await page(button.dataset.visibilityUrl);
      var form = doc.querySelector('form[data-builder-action]');
      if (!form) throw new Error('Не удалось открыть выбор номеров');
      if (dialog.open && dialog.contains(button)) recipientHistory.push(dialog.querySelector('form'));
      else recipientHistory = [];
      form.querySelector('[data-recipient-back]').hidden = !recipientHistory.length;
      dialog.replaceChildren(form);
      if (form.elements.due_action) form.elements.due_at.disabled = form.elements.due_action.value !== 'set';
      form.querySelectorAll('[data-mixed]').forEach(function (input) { input.indeterminate = true; });
      if (!dialog.open) dialog.showModal();
    } catch (error) {
      window.EgorAutosave.showSaved(false, error.message);
    } finally { busy = false; button.disabled = false; }
  });

  document.addEventListener('submit', async function (e) {
    var form = e.target.closest('[data-builder-action], [data-share-comment], [data-share-toggle]');
    if (!form) return;
    e.preventDefault();
    if (busy) return;
    busy = true;
    var data = new FormData(form), button = e.submitter, saved = false;
    if (button) button.disabled = true;
    try {
      var result = await window.EgorProblem.request(form.action, data);
      saved = true;
      var modal = form.closest('dialog');
      if (modal) modal.close();
      if (form.matches('[data-share-comment]')) {
        var share = form.closest('.ws-share-link'), value = data.get('comment').trim();
        var comment = share.querySelector('[data-share-comment-text]');
        comment.textContent = '(' + value + ')'; comment.hidden = !value;
        form.elements.comment.value = value; form.elements.comment.defaultValue = value;
        form.hidden = true;
      } else if (form.matches('[data-share-toggle]')) {
        form.querySelector('button').textContent = result.is_active ? 'отключить' : 'включить';
        form.closest('.ws-share-link').querySelector('[data-share-disabled]').hidden = result.is_active;
      } else await refresh();
      if (form.hasAttribute('data-reset-on-success')) form.reset();
      window.EgorAutosave.showSaved(true, result.message);
    } catch (error) {
      window.EgorAutosave.showSaved(false, saved
        ? 'Сохранено, но не удалось обновить вид листка. Обновите страницу.' : error.message);
    } finally { busy = false; if (button) button.disabled = false; }
  });
})();
