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

  // Фильтры колонки листков: «Найти листок…» по названию, раздел
  // рубрикатора («листалка» Арифметика / Алгебра / Геометрия…) и «Тема ▾»
  // внутри раздела (ревизия 03.11, P3: темы — над колонкой вместо панели).
  // Условия применяются вместе; тема — id группы [data-authored-group],
  // раздел — data-root строки (корень главной темы листка).
  function setupFilter(browser) {
    var wrap = document.querySelector('[data-authored-filter-wrap]');
    var input = document.querySelector('[data-authored-filter]');
    var menu = document.querySelector('[data-authored-topic-menu]');
    var roots = document.querySelector('[data-authored-roots]');
    var empty = browser.querySelector('[data-authored-empty]');
    var topic = '';
    var root = '';

    function apply() {
      var query = input ? input.value.trim().toLowerCase() : '';
      var shown = 0;
      browser.querySelectorAll('[data-authored-group]').forEach(function (group) {
        var visible = 0;
        var inTopic = !topic || group.id === topic;
        group.querySelectorAll('[data-authored-row]').forEach(function (row) {
          var title = row.querySelector('[data-authored-title]');
          var name = (title ? title.textContent : row.textContent).toLowerCase();
          var match = inTopic && (!root || row.dataset.root === root)
            && (!query || name.indexOf(query) !== -1);
          row.hidden = !match;
          if (match) visible += 1;
        });
        group.hidden = !visible;
        // В таблице свёрнутая глава с найденным листком раскрывается
        if ((query || topic || root) && visible && group.tagName === 'DETAILS') group.open = true;
        shown += visible;
      });
      if (empty) empty.hidden = shown > 0;
    }

    function setTopic(link) {
      if (!menu) return;
      var anchor = link ? link.dataset.authoredTopic : '';
      topic = anchor;
      menu.querySelectorAll('a[data-authored-topic]').forEach(function (a) {
        a.classList.toggle('is-current', a.dataset.authoredTopic === anchor);
      });
      var label = menu.querySelector('[data-authored-topic-label]');
      if (label) label.textContent = anchor ? link.firstChild.textContent.trim() : 'Все темы';
      menu.classList.toggle('is-set', Boolean(anchor));
    }

    // Раздел: в «Тема ▾» остаются темы раздела; выбранная тема другого
    // раздела сбрасывается.
    function setRoot(link) {
      root = link.dataset.authoredRoot;
      roots.querySelectorAll('a[data-authored-root]').forEach(function (a) {
        var on = a === link;
        a.classList.toggle('is-active', on);
        if (on) a.setAttribute('aria-current', 'true');
        else a.removeAttribute('aria-current');
      });
      if (menu) {
        menu.querySelectorAll('a[data-authored-topic]').forEach(function (a) {
          if (!a.dataset.authoredTopic) return;
          a.hidden = Boolean(root) && a.dataset.root !== root;
        });
        var total = menu.querySelector('[data-authored-topic-total]');
        if (total) total.textContent = link.dataset.count;
        var current = topic && menu.querySelector(
          'a[data-authored-topic="' + CSS.escape(topic) + '"]');
        if (current && current.hidden) setTopic(null);
      }
      history.replaceState(null, '', root
        ? '#' + link.getAttribute('href').split('#')[1]
        : location.pathname + location.search);
      apply();
    }

    if (wrap && input) {
      wrap.hidden = false;
      input.addEventListener('input', apply);
    }
    if (roots) {
      roots.addEventListener('click', function (event) {
        var link = event.target.closest('a[data-authored-root]');
        if (!link) return;
        event.preventDefault();
        setRoot(link);
      });
    }
    if (menu) {
      menu.addEventListener('click', function (event) {
        var link = event.target.closest('a[data-authored-topic]');
        if (!link) return;
        var anchor = link.dataset.authoredTopic;
        // Группы темы нет на странице (сортировка не по теме) — обычный переход
        if (anchor && !document.getElementById(anchor)) return;
        event.preventDefault();
        setTopic(anchor ? link : null);
        menu.open = false;
        apply();
      });
    }
    // Пришли по ссылке с якорем раздела или темы — сразу показываем только его
    var initial = location.hash.slice(1);
    if (initial) {
      var startRoot = roots && roots.querySelector(
        'a[href="#' + CSS.escape(initial) + '"]');
      var startTopic = menu && menu.querySelector(
        'a[data-authored-topic="' + CSS.escape(initial) + '"]');
      if (startRoot) startRoot.click();
      else if (startTopic) startTopic.click();
    }
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
