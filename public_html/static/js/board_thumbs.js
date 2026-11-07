/* Миниатюра доски ученика в окне «задача у ученика» (карта ответов):
   <canvas data-board-thumb data-url="…/canvas/<task>/">. Один запрос JSON
   этой доски, рисуется последняя непустая страница (EgorCanvas.render из
   canvas.js) — без виджета и без загрузки досок всей карты. Окно приходит
   фрагментом, поэтому миниатюры ищем и в добавленных узлах. */
(function () {
  'use strict';
  var SIZE = 240;
  function filled(page) {
    return (page.student && page.student.elements.length) || (page.teacher && page.teacher.elements.length);
  }
  function draw(canvas) {
    var key = canvas.dataset.url + '#' + (canvas.dataset.version || '');
    if (!window.EgorCanvas || canvas.dataset.drawn === key) return;
    canvas.dataset.drawn = key;
    fetch(canvas.dataset.url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        var pages = (data && data.pages) || [], page = pages.filter(filled).pop() || pages[pages.length - 1];
        if (page && document.body.contains(canvas)) EgorCanvas.render(canvas, page, SIZE);
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
