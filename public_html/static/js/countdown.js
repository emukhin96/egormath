/* Обратный отсчёт в кабинете ученика (accounts/dashboard_student.html):
   [data-countdown] — «мм:сс» до data-ends по часам сервера (data-now);
   data-bar — id полосы, чья ширина = доля прошедшего из data-total минут.
   На нуле страница перезагружается: работа уже сдана, статус сменился. */
(function () {
  'use strict';
  const clocks = [...document.querySelectorAll('[data-countdown]')].map(el => ({
    el,
    left: Date.parse(el.dataset.ends) - Date.parse(el.dataset.now),
    total: Number(el.dataset.total) * 60000 || 0,
    bar: el.dataset.bar ? document.getElementById(el.dataset.bar) : null,
  }));
  if (!clocks.length) return;
  const started = performance.now();
  let reloading = false;
  function tick() {
    const passed = performance.now() - started;
    clocks.forEach(clock => {
      const ms = clock.left - passed;
      const seconds = Math.max(0, Math.ceil(ms / 1000));
      clock.el.textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
      if (clock.bar && clock.total) clock.bar.style.width = Math.min(100, 100 - 100 * Math.max(0, ms) / clock.total) + '%';
      if (ms <= 0 && !reloading) { reloading = true; setTimeout(() => location.reload(), 1500); }
    });
  }
  setInterval(tick, 1000);
  tick();
})();
