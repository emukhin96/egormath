/* Страница «Доски»: боковая панель «Условия задач» справа.
   Немодальная: доски под ней остаются видны и продолжают обновляться
   (boards.js её не касается). Условия всех задач листка приходят фрагментом
   по первому открытию — страница досок с живым опросом их не ждёт.
   Задача из фильтра ?task= выделена фоном, панель прокручена к ней.
   Esc закрывает панель; открыта ли она — помним в sessionStorage. */
(function () {
  'use strict';
  var panel = document.querySelector('[data-peek-panel]');
  var toggle = document.querySelector('[data-peek-panel-toggle]');
  if (!panel || !toggle) return;
  var body = panel.querySelector('[data-peek-panel-body]');
  var key = panel.dataset.storageKey, loaded = false, loading = false;

  function remember(value) {
    try { if (value) sessionStorage.setItem(key, '1'); else sessionStorage.removeItem(key); } catch (e) { /* без хранилища — просто не помним */ }
  }
  function remembered() {
    try { return sessionStorage.getItem(key) === '1'; } catch (e) { return false; }
  }
  function scrollToCurrent() {
    var current = body.querySelector('.boards-peek-task.is-current');
    if (current) body.scrollTop += current.getBoundingClientRect().top - body.getBoundingClientRect().top - 8;
  }
  function load() {
    if (loaded || loading) return;
    loading = true;
    fetch(panel.dataset.url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (html) {
        body.innerHTML = html;
        loaded = true;
        if (window.renderMathContent) body.querySelectorAll('.math-content').forEach(window.renderMathContent);
        scrollToCurrent();
      })
      .catch(function () {
        body.innerHTML = '<p class="helptext">Не удалось загрузить условия. Закройте панель и откройте ещё раз.</p>';
      })
      .finally(function () { loading = false; });
  }
  function setOpen(value) {
    panel.hidden = !value;
    toggle.setAttribute('aria-expanded', String(value));
    document.body.classList.toggle('boards-peek-open', value);
    remember(value);
    if (value) { load(); if (loaded) scrollToCurrent(); }
  }

  toggle.addEventListener('click', function () { setOpen(panel.hidden); });
  panel.querySelector('[data-peek-panel-close]').addEventListener('click', function () {
    setOpen(false);
    toggle.focus();
  });
  document.addEventListener('keydown', function (e) {
    /* Esc в открытом диалоге доски закрывает диалог, а не панель */
    if (e.key !== 'Escape' || panel.hidden || document.querySelector('dialog[open]')) return;
    setOpen(false);
  });
  if (remembered()) setOpen(true);
})();
