/* Подтверждение конкретной версии ответа, серверное время и живой прогресс. */
(function () {
  'use strict';
  const forms = [...document.querySelectorAll('[data-iw-answer]')];
  const states = new Map();
  let expired = false;
  // Состояние ответа (макет A2): saved — зелёный, wrong и error — красный,
  // empty — серый; dirty и saving номер в ленте не перекрашивают.
  const strip = new Map([...document.querySelectorAll('[data-iw-strip]')].map(item => [item.dataset.iwStrip, item]));
  const counter = document.querySelector('[data-iw-answered]');
  function plural(n, forms) {
    const mod10 = n % 10, mod100 = n % 100;
    return forms[mod10 === 1 && mod100 !== 11 ? 0 : mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20) ? 1 : 2];
  }
  function recount() {
    if (!counter) return;
    const answered = [...strip.values()].filter(item => item.dataset.state !== 'empty').length;
    counter.textContent = answered + ' ' + plural(answered, ['ответ', 'ответа', 'ответов']);
  }
  function filled(form) {
    return [...dataOf(form)].some(([name, value]) => name !== 'version' && name !== 'csrfmiddlewaretoken' && String(value).trim());
  }
  function message(state, text, error, kind) {
    if (state.status) { state.status.textContent = text; state.status.classList.toggle('iw-save-error', !!error); }
    const mark = error ? 'error' : kind;
    if (!mark) return;
    state.form.dataset.state = mark;
    if (state.status) state.status.dataset.state = mark;
    const item = strip.get(state.form.dataset.point);
    if (item && mark !== 'dirty' && mark !== 'saving') { item.dataset.state = mark; recount(); }
  }
  function savedText(form) { return filled(form) ? ['Сохранено', 'saved'] : ['Ответа пока нет', 'empty']; }
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
    message(state, 'Сохраняется…', false, 'saving');
    const request = (async () => {
      const response = await fetch(form.action, {method: 'POST', body: data, headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const result = await response.json();
      if (!response.ok) { if (response.status === 409) state.conflict = true; throw new Error(result.message || 'Ошибка сохранения'); }
      form.elements.version.value = result.version;
      state.saved = sent;
      if (signature(form) === sent) { const [text, kind] = savedText(form); message(state, text, false, kind); }
      else message(state, 'Изменено, ещё не сохранено', false, 'dirty');
    })();
    state.pending = request;
    try { await request; } catch (error) { message(state, 'Не сохранено: ' + error.message, true); throw error; }
    finally { if (state.pending === request) state.pending = null; }
    if (signature(form) !== state.saved && !expired) await save(form);
  }
  forms.forEach(form => {
    const state = {form, saved: Number(form.elements.version.value) > 0 ? signature(form) : null, pending: null, timer: null, conflict: false, status: form.querySelector('[data-iw-save-status]')};
    states.set(form, state);
    const changed = () => {
      if (expired) return;
      clearChecks(form);
      if (signature(form) === state.saved) { const [text, kind] = savedText(form); message(state, text, false, kind); }
      else message(state, 'Изменено, ещё не сохранено', false, 'dirty');
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
        const verdicts = Object.values(result.checks || {});
        if (verdicts.includes('wrong')) message(state, 'Неверно — исправьте ответ', false, 'wrong');
        else if (verdicts.includes('ok')) message(state, 'Верно, сохранено', false, 'saved');
        else message(state, result.message || 'Проверено');
      })();
      state.pending = checking;
      try {
        await checking;
      } catch (error) {
        message(state, 'Не проверено: ' + error.message, true);
      } finally {
        if (state.pending === checking) state.pending = null;
        checkButton.disabled = false;
      }
    });
  });
  document.querySelectorAll('[data-iw-flush]').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;
    const button = form.querySelector('button');
    button.disabled = true;
    try { for (const answer of forms) await save(answer); form.submit(); }
    catch (error) { if (window.EgorAutosave) EgorAutosave.showSaved(false, error.message); button.disabled = false; }
  }));
  const timer = document.querySelector('[data-iw-timer]');
  if (timer) {
    const started = performance.now(), remaining = Date.parse(timer.dataset.ends) - Date.parse(timer.dataset.now);
    const bar = document.querySelector('[data-iw-time-bar]'), total = Number(timer.dataset.total) * 60000 || 0;
    function tick() {
      const ms = remaining - (performance.now() - started);
      const seconds = Math.max(0, Math.ceil(ms / 1000));
      timer.textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
      if (bar && total) bar.style.width = Math.min(100, 100 - 100 * Math.max(0, ms) / total) + '%';
      if (ms <= 0 && !expired) {
        expired = true;
        forms.forEach(form => [...form.elements].forEach(el => el.disabled = true));
        location.reload();
      }
    }
    setInterval(tick, 250); tick();
  }
  // Одно задание на экран (макет A2): видна секция из #point-N, номер в
  // ленте обведён. Без скрипта лист остаётся целиком.
  const sheet = document.querySelector('[data-iw-focus]');
  if (sheet) {
    const sections = [...sheet.querySelectorAll('.iw-point')];
    function show() {
      const match = location.hash.match(/^#point-(\d+)$/);
      const target = sections.find(section => match && section.id === 'point-' + match[1]) || sections[0];
      if (!target) return;
      sections.forEach(section => section.classList.toggle('is-current', section === target));
      strip.forEach((item, key) => {
        if ('point-' + key === target.id) { item.setAttribute('aria-current', 'step'); item.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
        else item.removeAttribute('aria-current');
      });
    }
    sheet.classList.add('is-focus');
    show();
    window.addEventListener('hashchange', () => { show(); window.scrollTo(0, 0); });
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
