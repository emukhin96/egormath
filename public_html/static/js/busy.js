/* Мгновенный отклик кнопок на долгие действия: класс .is-busy со спиннером.
   EgorBusy.start(btn, 'Собираем…') / EgorBusy.stop(btn) — из кода;
   ссылки и кнопки с data-busy="Открываем…" получают то же состояние по
   клику (переход на тяжёлую страницу), при возврате «назад» из bfcache
   состояние снимается. */
(function () {
  'use strict';

  function start(btn, label) {
    if (!btn || btn.classList.contains('is-busy')) return;
    btn.dataset.idleLabel = btn.textContent;
    // Ширина не прыгает, когда подпись становится короче
    btn.style.minWidth = btn.offsetWidth + 'px';
    btn.classList.add('is-busy');
    btn.setAttribute('aria-busy', 'true');
    if (label) btn.textContent = label;
  }

  function stop(btn) {
    if (!btn || !btn.classList.contains('is-busy')) return;
    btn.classList.remove('is-busy');
    btn.removeAttribute('aria-busy');
    btn.style.minWidth = '';
    if (btn.dataset.idleLabel !== undefined) {
      btn.textContent = btn.dataset.idleLabel;
      delete btn.dataset.idleLabel;
    }
  }

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-busy]');
    if (!el || e.defaultPrevented) return;
    // Открытие в новой вкладке не уводит со страницы — спиннер не нужен
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey
        || el.target === '_blank') return;
    start(el, el.dataset.busy);
  });

  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    document.querySelectorAll('[data-busy].is-busy').forEach(stop);
  });

  window.EgorBusy = {start: start, stop: stop};
})();
