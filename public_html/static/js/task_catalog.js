/* Видимость материалов каталога сохраняется между страницами поиска. */
(function () {
  var toggle = document.getElementById('toggle-catalog-answers');
  if (!toggle) return;
  try { toggle.checked = sessionStorage.getItem('catalog-answers') === '1'; } catch (_) {}
  function display() {
    document.querySelectorAll('.task-catalog .ws-answers').forEach(function (el) {
      el.hidden = !toggle.checked;
      if (toggle.checked) el.querySelectorAll('.math-content').forEach(renderMathContent);
    });
    try { sessionStorage.setItem('catalog-answers', toggle.checked ? '1' : '0'); } catch (_) {}
  }
  toggle.addEventListener('change', display); display();
})();

/* Тумблер редактора «Показывать задачи других учителей»: форма #task-list-prefs
   возвращает на адрес из скрытого поля next, а живой поиск (task_finder.js)
   меняет фильтры через replaceState без перезагрузки — поэтому next
   подставляется из текущего адреса в момент отправки, а не при отрисовке. */
(function () {
  var form = document.getElementById('task-list-prefs');
  if (!form) return;
  form.addEventListener('submit', function () {
    var next = form.querySelector('input[name="next"]');
    if (next) next.value = location.pathname + location.search;
  });
})();

/* Класс и темы в строке каталога: текст сводки обновляется после правки в
   раскрытом блоке — класс по селекту, темы по чипам выбора темы. */
(function () {
  // Как в шаблоне строки: код темы, если он есть, иначе название до 28 символов.
  // Код и название берутся из data-атрибутов чипа (taxonomy.js), текст метки не разбирается.
  var NAME_LIMIT = 28;
  function truncate(text) {
    return text.length > NAME_LIMIT ? text.slice(0, NAME_LIMIT - 1) + '…' : text;
  }
  function refresh(details) {
    var grade = details.querySelector('select[name="grade_level"]');
    var gradeOut = details.querySelector('[data-row-edit-grade]');
    if (grade && gradeOut) {
      var option = grade.options[grade.selectedIndex];
      var text = option ? option.text.trim() : '';
      gradeOut.textContent = (text && text !== '—') ? text : '—';
    }
    var topicsOut = details.querySelector('[data-row-edit-topics]');
    if (!topicsOut) return;
    // Смотрим только на контейнер чипов: пока каталог тем не загружен, он пуст,
    // а при ошибке загрузки .tax-empty появляется в другом месте — сводку не трогаем.
    var chips = details.querySelector('[data-tax-chips]');
    if (!chips || !chips.querySelector('.tax-chip, .tax-empty')) return;
    var labels = Array.prototype.map.call(chips.querySelectorAll('.tax-chip'), function (chip) {
      var code = (chip.dataset.topicCode || '').trim();
      var name = (chip.dataset.topicName || '').trim();
      return code || truncate(name);
    }).filter(Boolean);
    topicsOut.textContent = labels.length ? labels.join(', ') : 'без темы';
  }
  function watch(details) {
    if (details.dataset.rowEditReady) return;
    details.dataset.rowEditReady = '1';
    details.addEventListener('change', function () { refresh(details); });
    // За чипами следим только после раскрытия блока: серверная сводка не
    // должна затираться первым рендером выбора темы до загрузки каталога.
    details.addEventListener('toggle', function () {
      if (!details.open || details.dataset.rowEditWatched) return;
      details.dataset.rowEditWatched = '1';
      var chips = details.querySelector('[data-tax-chips]');
      if (chips && window.MutationObserver) {
        new MutationObserver(function () { refresh(details); })
          .observe(chips, {childList: true, subtree: true, characterData: true});
      }
    });
  }
  function init() {
    document.querySelectorAll('[data-row-edit]').forEach(watch);
  }
  document.addEventListener('DOMContentLoaded', init);
  // Живой поиск подменяет таблицу — наблюдаем за новыми строками.
  if (window.MutationObserver) {
    new MutationObserver(init).observe(document.documentElement, {childList: true, subtree: true});
  }
})();
