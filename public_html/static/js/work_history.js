/* История загружается только при раскрытии; пагинация не обновляет работу. */
(function () {
  'use strict';
  async function load(details, url) {
    const body = details.querySelector('[data-audit-body]');
    if (details.dataset.loading) return;
    details.dataset.loading = '1';
    body.textContent = 'Загружается…';
    try {
      const response = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
      if (!response.ok || response.redirected) throw new Error();
      body.innerHTML = await response.text();
      body.querySelectorAll('[data-audit-page]').forEach(link => {
        link.href = new URL(link.getAttribute('href'), response.url).href;
      });
      details.dataset.loaded = '1';
    } catch (_) {
      body.textContent = 'Не удалось загрузить. Закройте и раскройте раздел, чтобы повторить.';
      delete details.dataset.loaded;
    } finally { delete details.dataset.loading; }
  }
  document.addEventListener('toggle', event => {
    const details = event.target;
    if (details.matches?.('details[data-audit-url]') && details.open && !details.dataset.loaded) load(details, details.dataset.auditUrl);
  }, true);
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-audit-page]');
    if (!link) return;
    const details = link.closest('[data-audit-url]');
    if (!details) return;
    event.preventDefault();
    load(details, link.href);
  });
})();
