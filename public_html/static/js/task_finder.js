/* Живой поиск задач: форма [data-finder] грузит ту же страницу с новыми
   параметрами и подменяет блоки [data-finder-target] (результаты, счётчики
   в сайдбаре), не перезагружая страницу. Адрес обновляется через
   replaceState, поэтому обновление страницы и «Сбросить» работают как
   раньше. Без JS форма отправляется обычным GET. */
(function () {
  'use strict';

  var form = document.querySelector('form[data-finder]');
  if (!form) return;
  var status = form.querySelector('[data-finder-status]');
  var timer = null, controller = null, sequence = 0;

  function targets(root) {
    return Array.prototype.slice.call(root.querySelectorAll('[data-finder-target]'));
  }

  function currentUrl() {
    var params = new URLSearchParams(new FormData(form));
    params.delete('page');
    var query = params.toString();
    return location.pathname + (query ? '?' + query : '')
      + (form.dataset.finderAnchor ? '#' + form.dataset.finderAnchor : '');
  }

  function busy(on) {
    targets(document).forEach(function (el) {
      el.classList.toggle('is-loading', on);
      el.setAttribute('aria-busy', on ? 'true' : 'false');
    });
    if (status) status.hidden = !on;
  }

  function rerun(root) {
    root.querySelectorAll('.math-content').forEach(function (el) {
      if (typeof renderMathContent === 'function') renderMathContent(el);
    });
    if (window.EgorTaxonomy) window.EgorTaxonomy.init();
    if (window.EgorBulk) window.EgorBulk.init();
    // Тумблеры ответов и масок перечитывают новые строки по этому событию.
    document.dispatchEvent(new CustomEvent('worksheet:updated', {detail: {finder: true}}));
    document.dispatchEvent(new CustomEvent('finder:updated', {detail: {root: root}}));
  }

  async function load(url, scroll) {
    if (controller) controller.abort();
    controller = new AbortController();
    var current = ++sequence;
    busy(true);
    try {
      var response = await fetch(url, {
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        signal: controller.signal,
      });
      if (!response.ok || response.redirected) throw new Error('Не удалось выполнить поиск. Повторите попытку.');
      var doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (current !== sequence) return;
      targets(document).forEach(function (el) {
        var fresh = doc.querySelector('[data-finder-target="' + el.dataset.finderTarget + '"]');
        if (fresh) {
          el.replaceWith(fresh);
          rerun(fresh);
        }
      });
      history.replaceState(null, '', url);
      if (scroll) {
        var first = targets(document)[0];
        if (first) first.scrollIntoView({block: 'start', behavior: 'smooth'});
      }
    } catch (error) {
      if (error.name === 'AbortError') return;
      if (window.EgorAutosave && window.EgorAutosave.showSaved) window.EgorAutosave.showSaved(false, error.message);
    } finally {
      if (current === sequence) busy(false);
    }
  }

  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(function () { load(currentUrl()); }, delay);
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearTimeout(timer);
    load(currentUrl());
  });
  form.addEventListener('input', function (event) {
    if (event.target.matches('[name="q"]')) schedule(350);
  });
  form.addEventListener('search', function (event) {
    if (event.target.matches('[name="q"]')) schedule(0);
  });

  // Страницы результатов — тоже без перезагрузки.
  document.addEventListener('click', function (event) {
    var link = event.target.closest('[data-finder-target] .pagination a[href]');
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
    event.preventDefault();
    var url = new URL(link.href, location.href);
    load(url.pathname + url.search + (form.dataset.finderAnchor ? '#' + form.dataset.finderAnchor : ''), true);
  });

  // Конструктор листка: после добавления задачи результаты перечитываются,
  // чтобы добавленная строка исчезла из поиска.
  if (form.dataset.finderAnchor) {
    document.addEventListener('worksheet:updated', function (event) {
      if (event.detail && event.detail.finder) return;
      if (form.querySelector('[name="q"]').value || form.querySelector('[name="grade"]').value) schedule(0);
    });
  }
})();
