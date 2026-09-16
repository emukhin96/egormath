/* Общий журнал работы: события пакетами, без текста буфера и нажатий клавиш. */
(function () {
  'use strict';
  const config = document.querySelector('[data-work-activity]');
  if (!config) return;
  const restricted = config.dataset.restricted === '1';
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  const page = crypto.randomUUID();
  const started = performance.now();
  let sequence = 0, pending = [], busy = false, lastOperation = -Infinity, retryAfter = 0;
  function log(kind, blocked = false) {
    // При недоступной сети очередь ограничена; журнал не является полным протоколом.
    if (pending.length >= 100) pending.shift();
    pending.push({id: crypto.randomUUID(), page, seq: sequence++, kind, blocked,
      at: new Date().toISOString(), elapsed: Math.min(86400000, Math.round(performance.now() - started))});
    if (pending.length >= 20) flush();
  }
  async function flush(leaving = false) {
    if (!pending.length || performance.now() < retryAfter || busy && !leaving) return;
    const batch = pending.slice(0, 20);
    if (leaving) {
      // Отправка при уходе не задерживает навигацию. Дубли устраняются сервером.
      fetch(config.dataset.workActivity, {method: 'POST', keepalive: true,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({events: batch})}).catch(() => {});
      return;
    }
    busy = true;
    try {
      const response = await fetch(config.dataset.workActivity, {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({events: batch})});
      if (!response.ok) retryAfter = performance.now() + 30000;
      if (response.ok || [400, 403, 404, 409, 413].includes(response.status)) {
        const ids = new Set(batch.map(row => row.id));
        pending = pending.filter(row => !ids.has(row.id));
      }
    } catch (_) { retryAfter = performance.now() + 30000; }
    finally { busy = false; }
  }
  document.addEventListener('visibilitychange', () => {
    log(document.hidden ? 'hidden' : 'visible');
    flush(document.hidden);
  });
  window.addEventListener('pagehide', () => flush(true));
  setInterval(() => flush(), 30000);
  function answerTarget(event) {
    return event.composedPath().some(node => node instanceof Element &&
      node.matches('[data-audit-answer], [data-audit-answer] *, #formula-panel, #formula-panel *'));
  }
  function selectionHasStatement() {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || selection.isCollapsed) return false;
    return [...document.querySelectorAll('[data-audit-statement]')].some(node => {
      for (let i = 0; i < selection.rangeCount; i++) {
        if (selection.getRangeAt(i).intersectsNode(node)) return true;
      }
      return false;
    });
  }
  function operation(event, kind) {
    if (restricted) {
      event.preventDefault();
      event.stopImmediatePropagation();
      window.EgorAutosave?.showSaved(false, 'Учитель ограничил копирование условий и вставку ответов.');
    }
    // paste и beforeinput одной операции не должны давать две записи.
    const now = performance.now();
    if (now - lastOperation > 100) log(kind, restricted);
    lastOperation = now;
  }
  document.addEventListener('copy', event => {
    if (!answerTarget(event) && selectionHasStatement()) operation(event, 'copy');
  }, true);
  document.addEventListener('paste', event => {
    if (answerTarget(event)) operation(event, 'paste');
  }, true);
  document.addEventListener('drop', event => {
    if (answerTarget(event) && !event.dataTransfer?.files.length &&
        [...(event.dataTransfer?.types || [])].some(type => type === 'text/plain' || type === 'text/html')) operation(event, 'drop');
  }, true);
  document.addEventListener('beforeinput', event => {
    if (answerTarget(event) && ['insertFromPaste', 'insertFromDrop'].includes(event.inputType)) {
      operation(event, event.inputType === 'insertFromDrop' ? 'drop' : 'paste');
    }
  }, true);
})();
