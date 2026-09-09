/* Видимость материалов каталога сохраняется между страницами поиска. */
(function () {
  var toggle = document.getElementById('toggle-catalog-answers');
  if (!toggle) return;
  try { toggle.checked = sessionStorage.getItem('catalog-answers') === '1'; } catch (_) {}
  function display() {
    document.querySelectorAll('.task-catalog .ws-answers').forEach(function (el) { el.hidden = !toggle.checked; });
    try { sessionStorage.setItem('catalog-answers', toggle.checked ? '1' : '0'); } catch (_) {}
  }
  toggle.addEventListener('change', display); display();
})();
