/* Обзор «Авторских листков».
   Строки списка — обычные ссылки ?sheet=<pk>: без JS сервер отдаёт страницу
   с выбранным листком. На широком экране клик подгружает фрагмент
   предпросмотра (/collections/<pk>/preview/) и подменяет правую панель;
   на узком (<760px) ведёт на отдельную страницу листка.
   Поле «Найти листок…» фильтрует строки списка и таблицы на клиенте. */
(function () {
  'use strict';

  var NARROW = window.matchMedia('(max-width: 759px)');

  function renderMath(root) {
    if (typeof renderMathContent !== 'function') return;
    root.querySelectorAll('.math-content').forEach(function (el) {
      if (el.closest('.ws-answers[hidden]')) return;
      renderMathContent(el);
    });
  }

  function setupFilter(browser) {
    var wrap = document.querySelector('[data-authored-filter-wrap]');
    var input = document.querySelector('[data-authored-filter]');
    if (!wrap || !input) return;
    wrap.hidden = false;
    var empty = browser.querySelector('[data-authored-empty]');
    input.addEventListener('input', function () {
      var query = input.value.trim().toLowerCase();
      var shown = 0;
      browser.querySelectorAll('[data-authored-group]').forEach(function (group) {
        var visible = 0;
        group.querySelectorAll('[data-authored-row]').forEach(function (row) {
          var title = row.querySelector('[data-authored-title]');
          var name = (title ? title.textContent : row.textContent).toLowerCase();
          var match = !query || name.indexOf(query) !== -1;
          row.hidden = !match;
          if (match) visible += 1;
        });
        group.hidden = !visible;
        // В таблице свёрнутая глава с найденным листком раскрывается
        if (query && visible && group.tagName === 'DETAILS') group.open = true;
        shown += visible;
      });
      if (empty) empty.hidden = shown > 0;
    });
  }

  function setupPreview(browser) {
    var pane = browser.querySelector('[data-authored-pane]');
    if (!pane) return;
    var pending = null;

    function markActive(link) {
      browser.querySelectorAll('.authored-li.is-active').forEach(function (el) {
        el.classList.remove('is-active');
        el.removeAttribute('aria-current');
      });
      link.classList.add('is-active');
      link.setAttribute('aria-current', 'true');
    }

    // Листок выбран без перезагрузки: форма сортировки и ссылки сегментов
    // должны его сохранять, как при выборе ссылкой ?sheet=.
    function syncSheet(head) {
      var pk = head.dataset.sheetPk;
      var sectionPk = head.dataset.sectionPk || '';
      var form = document.querySelector('form[data-autosubmit]');
      if (form) {
        var input = form.querySelector('input[name="sheet"]');
        if (!input) {
          input = document.createElement('input');
          input.type = 'hidden';
          input.name = 'sheet';
          form.appendChild(input);
        }
        input.value = pk;
      }
      document.querySelectorAll('a[data-sheet-scope]').forEach(function (a) {
        var scope = a.dataset.sheetScope;
        var url = new URL(a.href, window.location.href);
        if (scope === 'all' || scope === sectionPk) url.searchParams.set('sheet', pk);
        else url.searchParams.delete('sheet');
        a.href = url.pathname + url.search;
      });
    }

    function swap(html) {
      var tmp = document.createElement('div');
      tmp.innerHTML = html;
      var head = tmp.querySelector('[data-authored-head]');
      var items = tmp.querySelector('#ws-items');
      var actions = tmp.querySelector('[data-authored-actions]');
      var oldHead = pane.querySelector('[data-authored-head]');
      var oldActions = pane.querySelector('[data-authored-actions]');
      var oldItems = pane.querySelector('#ws-items');
      if (!head || !items || !actions || !oldHead || !oldItems || !oldActions) return false;
      oldHead.replaceWith(head);
      syncSheet(head);
      oldActions.replaceWith(actions);
      // #ws-items остаётся тем же узлом со своими классами: на него подписаны
      // тумблеры ответов (show-answers, author-only). Из фрагмента берём
      // только ширину колонки номеров.
      oldItems.classList.toggle('ws-num-wide', items.classList.contains('ws-num-wide'));
      oldItems.setAttribute('style', items.getAttribute('style') || '');
      oldItems.innerHTML = items.innerHTML;
      document.dispatchEvent(new CustomEvent('worksheet:updated'));
      renderMath(pane);
      return true;
    }

    browser.addEventListener('click', function (event) {
      var link = event.target.closest('a.authored-li');
      if (!link || event.defaultPrevented || event.button !== 0
          || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      if (NARROW.matches) {
        window.location.href = link.dataset.detailUrl;
        return;
      }
      if (pending) pending.abort();
      var controller = pending = new AbortController();
      markActive(link);
      pane.classList.add('is-loading');
      var url = link.dataset.previewUrl + '?next=' + encodeURIComponent(
        link.pathname + link.search);
      fetch(url, {
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        credentials: 'same-origin',
        signal: controller.signal,
      }).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      }).then(function (html) {
        if (!swap(html)) throw new Error('bad fragment');
        browser.classList.add('has-sheet');
        history.replaceState(null, '', link.href);
        // Начало листка уехало выше топбара — возвращаем его в поле зрения
        var topbar = document.querySelector('.topbar');
        var offset = (topbar ? topbar.offsetHeight : 0) + 16;
        var top = pane.getBoundingClientRect().top;
        if (top < offset) window.scrollBy(0, top - offset);
      }).catch(function (error) {
        if (error && error.name === 'AbortError') return;
        window.location.href = link.href;
      }).then(function () {
        if (pending === controller) pane.classList.remove('is-loading');
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var browser = document.querySelector('[data-authored-browser]');
    if (!browser) return;
    setupFilter(browser);
    setupPreview(browser);
  });
})();
