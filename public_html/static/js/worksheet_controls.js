/* Действия конструктора без навигации и выбор номеров для получателя. */
(function () {
  'use strict';
  var list = document.getElementById('ws-items');
  if (!list) return;
  var dialog = document.getElementById('recipient-visibility-dialog');
  var busy = false;

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
    document.dispatchEvent(new CustomEvent('worksheet:updated'));
  }

  document.addEventListener('click', async function (e) {
    var dismiss = e.target.closest('[data-undo-dismiss]');
    if (dismiss) dismiss.closest('.undo-bar').hidden = true;
    var select = e.target.closest('[data-visibility-select]');
    if (select) {
      select.form.querySelectorAll('[name=visible_items]').forEach(function (input) {
        input.checked = select.dataset.visibilitySelect === 'all';
      });
    }
    var button = e.target.closest('[data-visibility-url]');
    if (!button || busy) return;
    busy = true;
    button.disabled = true;
    try {
      var doc = await page(button.dataset.visibilityUrl);
      var form = doc.querySelector('form[data-builder-action]');
      if (!form) throw new Error('Не удалось открыть выбор номеров');
      dialog.replaceChildren(form);
      dialog.showModal();
    } catch (error) {
      window.EgorAutosave.showSaved(false, error.message);
    } finally { busy = false; button.disabled = false; }
  });

  document.addEventListener('submit', async function (e) {
    var form = e.target.closest('[data-builder-action]');
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
      await refresh();
      window.EgorAutosave.showSaved(true, result.message);
    } catch (error) {
      window.EgorAutosave.showSaved(false, saved
        ? 'Сохранено, но не удалось обновить вид листка. Обновите страницу.' : error.message);
    } finally { busy = false; if (button) button.disabled = false; }
  });
})();
