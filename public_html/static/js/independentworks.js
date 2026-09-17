/* Подтверждение конкретной версии ответа, серверное время и живой прогресс. */
(function () {
  'use strict';
  const forms = [...document.querySelectorAll('[data-iw-answer]')];
  const states = new Map();
  let expired = false;
  function message(state, text, error) {
    if (state.status) { state.status.textContent = text; state.status.classList.toggle('iw-save-error', !!error); }
  }
  function dataOf(form) { return new FormData(form); }
  function signature(form) {
    return JSON.stringify([...dataOf(form)].filter(([name]) => name !== 'version' && name !== 'csrfmiddlewaretoken'));
  }
  function clearChecks(form) {
    form.querySelectorAll('[data-check]').forEach(holder => {
      if (window.EgorCheckBadge) EgorCheckBadge.render(holder, '');
      else { holder.dataset.status = ''; holder.textContent = ''; }
    });
  }
  async function save(form) {
    const state = states.get(form);
    if (state.pending) { await state.pending; return save(form); }
    if (state.conflict) throw new Error('Конфликт вкладок: перезагрузите страницу, сохранив свой текст.');
    if (expired || signature(form) === state.saved) return;
    const sent = signature(form), data = dataOf(form);
    message(state, 'Сохраняется…');
    const request = (async () => {
      const response = await fetch(form.action, {method: 'POST', body: data, headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const result = await response.json();
      if (!response.ok) { if (response.status === 409) state.conflict = true; throw new Error(result.message || 'Ошибка сохранения'); }
      form.elements.version.value = result.version;
      state.saved = sent;
      message(state, signature(form) === sent ? '✓ Сохранён' : 'Изменён, ещё не сохранён');
    })();
    state.pending = request;
    try { await request; } catch (error) { message(state, error.message, true); throw error; }
    finally { if (state.pending === request) state.pending = null; }
    if (signature(form) !== state.saved && !expired) await save(form);
  }
  forms.forEach(form => {
    const state = {saved: Number(form.elements.version.value) > 0 ? signature(form) : null, pending: null, timer: null, conflict: false, status: form.querySelector('[data-iw-save-status]')};
    states.set(form, state);
    const changed = () => {
      if (expired) return;
      clearChecks(form);
      message(state, signature(form) === state.saved ? '✓ Сохранён' : 'Изменён, ещё не сохранён');
      clearTimeout(state.timer);
      state.timer = setTimeout(() => save(form).catch(() => {}), 500);
    };
    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    form.addEventListener('focusout', () => save(form).catch(() => {}));
    form.addEventListener('submit', event => { event.preventDefault(); save(form).catch(() => {}); });
    const checkButton = form.querySelector('[data-iw-check]');
    if (checkButton) checkButton.addEventListener('click', async () => {
      const state = states.get(form);
      clearTimeout(state.timer);
      checkButton.disabled = true;
      const previous = state.pending;
      const checking = (async () => {
        if (previous) await previous;
        const data = dataOf(form);
        const response = await fetch(checkButton.getAttribute('formaction'), {
          method: 'POST', body: data, headers: {'X-Requested-With': 'XMLHttpRequest'}
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || 'Ошибка проверки');
        if (result.version !== undefined) {
          form.elements.version.value = result.version;
          state.saved = signature(form);
        }
        if (window.EgorCheckBadge) EgorCheckBadge.apply(form, result.checks || {});
        message(state, result.message || 'Проверено');
      })();
      state.pending = checking;
      try {
        await checking;
      } catch (error) {
        message(state, error.message, true);
      } finally {
        if (state.pending === checking) state.pending = null;
        checkButton.disabled = false;
      }
    });
  });
  document.querySelectorAll('[data-iw-flush]').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try { for (const answer of forms) await save(answer); form.submit(); }
    catch (error) { if (window.EgorAutosave) EgorAutosave.showSaved(false, error.message); button.disabled = false; }
  }));
  const timer = document.querySelector('[data-iw-timer]');
  if (timer) {
    const started = performance.now(), remaining = Date.parse(timer.dataset.ends) - Date.parse(timer.dataset.now);
    function tick() {
      const ms = remaining - (performance.now() - started);
      const seconds = Math.max(0, Math.ceil(ms / 1000));
      timer.textContent = 'Осталось ' + Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
      if (ms <= 0 && !expired) {
        expired = true;
        forms.forEach(form => [...form.elements].forEach(el => el.disabled = true));
        location.reload();
      }
    }
    setInterval(tick, 250); tick();
  }
  const progress = document.querySelector('[data-iw-progress]');
  if (progress) {
    let etag = '', busy = false;
    async function poll() {
      if (document.hidden || busy) return;
      busy = true;
      try {
        const url = new URL(location.href); url.searchParams.set('fragment', '1');
        const response = await fetch(url, {headers: etag ? {'If-None-Match': etag} : {}});
        if (response.status !== 304) {
          if (!response.ok) throw new Error('Ошибка обновления');
          const x = progress.querySelector('.iw-table-wrap')?.scrollLeft || 0;
          progress.innerHTML = await response.text();
          if (progress.querySelector('.iw-table-wrap')) progress.querySelector('.iw-table-wrap').scrollLeft = x;
          etag = response.headers.get('ETag') || '';
        }
        document.querySelector('[data-iw-live-status]').textContent = 'Обновлено ' + new Date().toLocaleTimeString();
      } catch (_) { document.querySelector('[data-iw-live-status]').textContent = 'Связь прервана. Повторим обновление.'; }
      finally { busy = false; }
    }
    setInterval(poll, 5000);
    document.addEventListener('visibilitychange', poll);
  }
})();
