/* Общий журнал работы: события пакетами, без нажатий клавиш. Из буфера
   записывается только скопированный текст условий (не вставленное). */
(function () {
  'use strict';
  const config = document.querySelector('[data-work-activity]');
  if (!config) return;
  // Две независимые настройки; при запрете копирования подменять нечего.
  const restricted = config.dataset.restricted === '1';
  const swap = config.dataset.swap === '1' && !restricted;
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  const page = crypto.randomUUID();
  const started = performance.now();
  let sequence = 0, pending = [], busy = false, lastOperation = -Infinity, retryAfter = 0;
  function log(kind, blocked = false, extra = {}) {
    // При недоступной сети очередь ограничена; журнал не является полным протоколом.
    if (pending.length >= 100) pending.shift();
    pending.push({id: crypto.randomUUID(), page, seq: sequence++, kind, blocked,
      at: new Date().toISOString(), elapsed: Math.min(86400000, Math.round(performance.now() - started)), ...extra});
    if (pending.length >= 20) flush();
  }
  function nextBatch() {
    // Копирования везут текст: пакет режется по размеру (сервер принимает до 128 КБ).
    const batch = [];
    let size = 0;
    for (const row of pending.slice(0, 20)) {
      size += new TextEncoder().encode(JSON.stringify(row)).length;
      if (batch.length && size > 60000) break;
      batch.push(row);
    }
    return batch;
  }
  async function flush(leaving = false) {
    if (!pending.length || performance.now() < retryAfter || busy && !leaving) return;
    const batch = nextBatch();
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
      // Копирование, сделанное во время отправки, не ждёт следующего таймера.
      if (response.ok && pending.some(row => row.kind === 'copy')) setTimeout(() => flush(), 1000);
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
  function operation(event, kind, extra = {}) {
    if (restricted) {
      event.preventDefault();
      event.stopImmediatePropagation();
      window.EgorAutosave?.showSaved(false, 'Ошибка');
    }
    // paste и beforeinput одной операции не должны давать две записи.
    const now = performance.now();
    if (now - lastOperation > 100) log(kind, restricted, extra);
    lastOperation = now;
  }

  const TEXT_LIMIT = 2000;
  // Номер задачи и звёзды сложности — не часть условия (и не числа для подмены).
  const NOT_STATEMENT = '.ws-num, .stars';
  // Чистый текст без дублей формул KaTeX — общий с копированием по сайту.
  function plainText(range) { return window.EgorCopy.plainText(range, NOT_STATEMENT); }
  function bare(text) { return text.replace(/\s+/g, ''); }
  // Какую долю каждого условия захватило выделение — по длине текста без пробелов.
  function statementShares(selection) {
    const shares = [];
    document.querySelectorAll('[data-audit-statement]').forEach(node => {
      const full = document.createRange();
      full.selectNodeContents(node);
      const length = bare(plainText(full)).length;
      if (!length) return;
      let covered = 0;
      for (let i = 0; i < selection.rangeCount; i++) {
        const range = selection.getRangeAt(i);
        if (!range.intersectsNode(node)) continue;
        const part = full.cloneRange();
        if (range.compareBoundaryPoints(Range.START_TO_START, part) > 0) part.setStart(range.startContainer, range.startOffset);
        if (range.compareBoundaryPoints(Range.END_TO_END, part) < 0) part.setEnd(range.endContainer, range.endOffset);
        covered += bare(plainText(part)).length;
      }
      if (covered) shares.push({label: (node.dataset.auditStatement || '').slice(0, 30),
        share: Math.min(100, Math.round(100 * covered / length))});
    });
    // Как и сервер — не больше 100 условий на одно копирование.
    return shares.slice(0, 100);
  }
  function selectionText(selection) { return window.EgorCopy.selectionText(selection, NOT_STATEMENT); }

  // Подмена чисел: показатели степени, индексы, номера точек (A1), 0, 1 и
  // «круглые» углы не трогаем — условие остаётся правдоподобным, но ответ по
  // нему другой. Одно и то же число на странице подменяется одинаково.
  const swaps = new Map();
  const KEEP = new Set(['0', '1', '90', '180', '360', '100']);
  function randomInt(low, high) { return low + Math.floor(Math.random() * (high - low + 1)); }
  function swapInteger(digits) {
    const value = Number(digits);
    if (digits.length === 1) {
      let other = value;
      while (other === value) other = randomInt(2, 9);
      return String(other);
    }
    const low = 10 ** (digits.length - 1), high = 10 ** digits.length - 1;
    const step = Math.max(1, Math.round(value * 0.15));
    for (let tries = 0; tries < 20; tries++) {
      const other = value + randomInt(1, step) * (Math.random() < 0.5 ? -1 : 1);
      if (other >= low && other <= high && other !== value) return String(other);
    }
    return String(value === high ? value - 1 : value + 1);
  }
  function candidate(token) {
    const match = token.match(/^(\d+)([.,])(\d+)$/);
    if (!match) return swapInteger(token);
    if (Number(match[1]) >= 2) return swapInteger(match[1]) + match[2] + match[3];
    // 0,25 → 0,29: меняется последняя цифра дробной части
    const last = match[3].slice(-1);
    let other = last;
    while (other === last) other = String(randomInt(1, 9));
    return match[1] + match[2] + match[3].slice(0, -1) + other;
  }
  function swapNumber(token) {
    if (KEEP.has(token)) return token;
    if (!swaps.has(token)) {
      // Разные числа условия не должны совпасть после подмены
      const used = new Set([...swaps.keys(), ...swaps.values()]);
      let other = candidate(token);
      for (let tries = 0; tries < 10 && used.has(other); tries++) other = candidate(token);
      swaps.set(token, other);
    }
    return swaps.get(token);
  }
  function swapNumbers(text) {
    return text.replace(/\d+(?:[.,]\d+)?/g, (token, offset) => {
      const before = text.slice(Math.max(0, offset - 7), offset);
      if (/(\^|_)\{?$|\\sqrt\[$|[A-Za-zА-Яа-яЁё]$/.test(before)) return token;
      return swapNumber(token);
    });
  }

  document.addEventListener('copy', event => {
    if (answerTarget(event) || !selectionHasStatement()) return;
    const selection = window.getSelection();
    const text = selectionText(selection);
    const extra = {text: text.slice(0, TEXT_LIMIT), statements: statementShares(selection)};
    if (swap && event.clipboardData && text) {
      const swapped = swapNumbers(text);
      event.clipboardData.setData('text/plain', swapped);
      event.preventDefault();
      extra.swapped = swapped.slice(0, TEXT_LIMIT);
    }
    operation(event, 'copy', extra);
    // Копирование видно учителю сразу, а не через 30 секунд.
    flush();
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
