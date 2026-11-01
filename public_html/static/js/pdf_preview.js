/* Панель предпросмотра PDF (редакторы листка и презентации) и её состояния:
   empty — ещё не собирали, busy — идёт сборка (спиннер и секундомер),
   ready — показан PDF, stale — PDF собран по прежним параметрам,
   error — сборка не удалась. Кнопки «Собрать PDF» на время сборки —
   в состоянии EgorBusy. */
(function () {
  'use strict';

  function formatElapsed(seconds) {
    var s = Math.floor(seconds);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  window.EgorPdfPreview = function (pane, buttons) {
    var frame = pane.querySelector('iframe');
    var elapsed = pane.querySelector('[data-pdf-elapsed]');
    var errorText = pane.querySelector('[data-pdf-error]');
    var timer = null;
    var startedAt = 0;

    function setState(state) {
      pane.dataset.state = state;
      if (state === 'busy') return;
      clearInterval(timer);
      timer = null;
      buttons.forEach(function (btn) { window.EgorBusy.stop(btn); });
    }

    function tick() {
      elapsed.textContent = formatElapsed((Date.now() - startedAt) / 1000);
    }

    return {
      busy: function () {
        frame.removeAttribute('src');
        startedAt = Date.now();
        tick();
        clearInterval(timer);
        timer = setInterval(tick, 1000);
        buttons.forEach(function (btn) {
          window.EgorBusy.start(btn, 'Собираем…');
        });
        setState('busy');
      },
      ready: function (src) {
        frame.src = src;
        setState('ready');
      },
      error: function (message) {
        errorText.textContent = message;
        setState('error');
      },
      // PDF на экране и текущие параметры разошлись (или снова совпали)
      stale: function (isStale) {
        var state = pane.dataset.state;
        if (state === 'ready' || state === 'stale') {
          setState(isStale ? 'stale' : 'ready');
        }
      },
    };
  };
})();
