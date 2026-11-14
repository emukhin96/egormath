/* Тумблер «ответы и решения»: #toggle-answers переключает .show-answers
   на #ws-items и атрибут hidden у блоков .ws-answers; #toggle-author-only
   (если есть) — класс .author-only, скрывающий AI-варианты.
   Ключ localStorage — data-answers-key (у подборки свой, чтобы не
   подхватывать состояние конструктора).

   Длинный листок (#ws-items[data-answers-url], порог —
   worksheets/builder_rows.py ANSWERS_INLINE_MAX) приходит без рамок ответов:
   при включённом тумблере они запрашиваются одним fetch
   (JSON {items: {id строки: HTML рамки}}) и вставляются в строки перед
   блоком масок; строки, появившиеся позже (worksheet:updated после
   добавления задачи), дозапрашиваются с ?items=. Формулы дорисовывает
   EgorMath (math.js) — по мере прокрутки на большой странице. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('toggle-answers');
    var list = document.getElementById('ws-items');
    if (!toggle || !list) return;
    var KEY = list.getAttribute('data-answers-key') || 'ws-show-answers';
    var answersUrl = list.getAttribute('data-answers-url');
    var loading = false;

    // Показ/скрытие рамок внутри root по состоянию тумблера
    function showAnswers(root) {
      var on = toggle.checked;
      // На большой странице формулы ответов дорисовываются по мере прокрутки
      // (EgorMath.observe, math.js), на маленькой — сразу, как раньше
      var render = window.EgorMath ? window.EgorMath.observe : renderMathContent;
      root.querySelectorAll('.ws-answers').forEach(function (el) {
        el.hidden = !on;
        if (on) el.querySelectorAll('.math-content').forEach(render);
      });
    }

    // Строки задач, в которые рамки ответов ещё не вставлялись
    function pendingRows() {
      return Array.prototype.slice.call(
        list.querySelectorAll('.ws-item[data-task-id]:not([data-answers-loaded])'));
    }

    function insertAnswers(row, html) {
      row.setAttribute('data-answers-loaded', '1');
      if (!html) return;
      // Место рамки — как в HTML короткого листка: после условия и рисунков,
      // перед блоком масок
      var anchor = row.querySelector('[data-worksheet-mask]');
      if (anchor) anchor.insertAdjacentHTML('beforebegin', html);
      else row.querySelector('.ws-content').insertAdjacentHTML('beforeend', html);
      showAnswers(row);
    }

    function loadAnswers(rows) {
      if (loading) return;
      loading = true;
      var ids = rows.map(function (row) { return row.dataset.id; });
      // Весь листок — одним запросом; после добавления задач — только новые строки
      var url = answersUrl;
      if (ids.length < list.querySelectorAll('.ws-item[data-task-id]').length) {
        url += (url.indexOf('?') === -1 ? '?' : '&') + 'items=' + ids.join(',');
      }
      fetch(url, {credentials: 'same-origin', headers: {Accept: 'application/json'}})
        .then(function (response) {
          if (!response.ok) throw new Error('answers ' + response.status);
          return response.json();
        })
        .then(function (data) {
          rows.forEach(function (row) {
            if (row.isConnected) insertAnswers(row, data.items[row.dataset.id] || '');
          });
        })
        .catch(function (error) {
          // Строки остались без data-answers-loaded: следующее включение
          // тумблера (или worksheet:updated) повторит запрос
          if (window.console) console.warn('Ответы листка не загрузились', error);
        })
        .then(function () {
          loading = false;
          // Пока ждали ответ, тумблер включали заново или добавили задачу
          if (toggle.checked && pendingRows().length) loadAnswers(pendingRows());
        });
    }

    function apply() {
      var on = toggle.checked;
      list.classList.toggle('show-answers', on);
      showAnswers(list);
      if (on && answersUrl && pendingRows().length) loadAnswers(pendingRows());
      try { localStorage.setItem(KEY, on ? '1' : ''); } catch (e) {}
    }
    try { toggle.checked = localStorage.getItem(KEY) === '1'; } catch (e) {}
    apply();
    toggle.addEventListener('change', apply);
    document.addEventListener('worksheet:updated', apply);

    // «Только из задачника»: #toggle-author-only прячет AI-ответы и решения
    // (.author-only на #ws-items, правила в input.css). Ключ — data-storage-key.
    var authorOnly = document.getElementById('toggle-author-only');
    if (!authorOnly) return;
    var AUTHOR_KEY = authorOnly.getAttribute('data-storage-key') || 'ws-author-only';
    function applyAuthorOnly() {
      list.classList.toggle('author-only', authorOnly.checked);
      try { localStorage.setItem(AUTHOR_KEY, authorOnly.checked ? '1' : ''); } catch (e) {}
    }
    try { authorOnly.checked = localStorage.getItem(AUTHOR_KEY) === '1'; } catch (e) {}
    applyAuthorOnly();
    authorOnly.addEventListener('change', applyAuthorOnly);
    // Список подменили скриптом (предпросмотр листка и т.п.) — состояние
    // тумблера применяется заново, как и у «ответов и решений».
    document.addEventListener('worksheet:updated', applyAuthorOnly);
  });
})();
