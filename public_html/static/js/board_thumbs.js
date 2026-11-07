/* Миниатюра доски ученика в окне «задача у ученика» (карта ответов):
   <canvas data-board-thumb data-url="…/canvas/<task>/">. Один запрос JSON
   этой доски, рисуется последняя непустая страница (EgorCanvas.render из
   canvas.js) — без виджета и без загрузки досок всей карты. Окно приходит
   фрагментом, поэтому миниатюры ищем и в добавленных узлах. Подключается
   из _progress_dialog.html — на всех страницах, где открывается это окно. */
(function () {
  'use strict';
  if (window.EgorBoardThumbs) return;   /* окно подключено на странице дважды */
  window.EgorBoardThumbs = true;
  var SIZE = 240;
  /* canvas.js (EgorCanvas.render) есть не на всех страницах с окном ответа
     (хронология, журнал, листок…): там он грузится один раз, когда в окне
     впервые появилась доска, — страницы без досок его не тянут */
  var canvasSrc = document.currentScript && document.currentScript.dataset.canvasSrc, loading = null;
  function canvasReady() {
    if (window.EgorCanvas) return Promise.resolve();
    if (!canvasSrc) return Promise.reject(new Error('нет canvas.js'));
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        var script = document.createElement('script');
        script.src = canvasSrc;
        script.onload = function () { window.EgorCanvas ? resolve() : reject(new Error('canvas.js без EgorCanvas')); };
        script.onerror = function () { loading = null; reject(new Error('canvas.js не загрузился')); };
        document.head.appendChild(script);
      });
    }
    return loading;
  }
  function filled(page) {
    return (page.student && page.student.elements.length) || (page.teacher && page.teacher.elements.length);
  }
  function draw(canvas) {
    var key = canvas.dataset.url + '#' + (canvas.dataset.version || '');
    if (canvas.dataset.drawn === key) return;
    canvas.dataset.drawn = key;
    canvasReady()
      .then(function () { return fetch(canvas.dataset.url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}}); })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        var pages = (data && data.pages) || [], page = pages.filter(filled).pop() || pages[pages.length - 1];
        if (!page || !document.body.contains(canvas)) return;
        EgorCanvas.render(canvas, page, SIZE);
        /* Квадрат показываем только нарисованным: без canvas.js или при ошибке — одни ссылки */
        var link = canvas.closest('.tw-board-thumb');
        if (link) link.hidden = false;
      })
      .catch(function () { delete canvas.dataset.drawn; });
  }
  function scan(root) {
    if (root.matches && root.matches('[data-board-thumb]')) draw(root);
    if (root.querySelectorAll) Array.prototype.forEach.call(root.querySelectorAll('[data-board-thumb]'), draw);
  }
  document.addEventListener('DOMContentLoaded', function () {
    scan(document);
    if (!window.MutationObserver) return;
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        Array.prototype.forEach.call(record.addedNodes, function (node) { if (node.nodeType === 1) scan(node); });
      });
    }).observe(document.body, {childList: true, subtree: true});
  });
})();
