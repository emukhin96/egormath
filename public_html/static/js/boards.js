/* Дашборд «Доски»: доски всех учеников листка на одном экране учителя.
   Один опрос на весь экран раз в POLL мс (304 — если ничего не менялось),
   перерисовываются только изменившиеся миниатюры. Клик по карточке открывает
   обычный виджет учителя (canvas.js) в диалоге; пока он открыт, сетка
   опрашивается реже. Через IDLE мс без движения мыши опрос останавливается
   («Продолжить»), чтобы забытая вкладка не дёргала сервер всю ночь. */
(function () {
  'use strict';
  var POLL = 5000, POLL_DIALOG = 15000, IDLE = 30 * 60 * 1000, THUMB = 300;
  var root = document.querySelector('[data-boards]');
  if (!root || !window.EgorCanvas) return;
  var liveUrl = root.dataset.liveUrl, taskFilter = parseInt(root.dataset.task || '0', 10) || 0;
  var status = document.querySelector('[data-boards-status]');
  var dialog = document.getElementById('boards-dialog');
  var since = null, etag = null, timer = null, lastActivity = Date.now(), stopped = false, busy = false;
  var latest = {};          /* assignment → последняя страница (payload) */
  var COPY_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var pagesOf = {};         /* assignment → {task: {task_no, canvas_url, count}} */
  var open = null;          /* {assignment, task} открытого диалога */

  function card(id) { return root.querySelector('[data-board="' + id + '"]'); }
  function ago(iso) {
    var s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 60) return s + ' с назад';
    if (s < 3600) return Math.round(s / 60) + ' мин назад';
    return new Date(iso).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
  }
  function ensureCard(state) {
    var el = card(state.assignment);
    if (el) return el;
    el = document.createElement('article');
    el.className = 'board-card'; el.dataset.board = state.assignment; el.tabIndex = 0; el.setAttribute('role', 'button');
    el.innerHTML = '<div class="board-meta"><strong class="board-name"></strong><span class="board-state" data-board-state></span></div>'
      + '<canvas class="board-thumb" width="300" height="300" aria-hidden="true"></canvas>'
      + '<div class="board-meta helptext"><span data-board-task>доски пока нет</span><span data-board-updated></span>'
      + '<button type="button" class="icon-btn board-copy" data-board-copy title="Скопировать доску как картинку" aria-label="Скопировать доску как картинку" hidden>' + COPY_ICON + '</button></div>';
    el.querySelector('.board-name').textContent = state.student;
    root.appendChild(el);
    return el;
  }
  function paint(page) {
    var el = card(page.assignment);
    if (!el) return;
    EgorCanvas.render(el.querySelector('canvas'), page, THUMB);
    el.querySelector('[data-board-task]').textContent = (taskFilter ? '' : 'задача ' + page.task_no + ', ') + 'стр. ' + page.number;
    el.querySelector('[data-board-updated]').textContent = ago(page.updated);
    el.dataset.updated = page.updated;
    var copyBtn = el.querySelector('[data-board-copy]');
    if (copyBtn) copyBtn.hidden = false;
    el.classList.add('board-fresh');
    setTimeout(function () { el.classList.remove('board-fresh'); }, 4000);
  }
  /* Кнопки задач над сеткой: пересобираются из tasks каждого ответа — новая
     первая доска по задаче добавляет кнопку, удаление последней — убирает */
  function syncTaskLinks(tasks) {
    var bar = document.querySelector('[data-boards-tasks]');
    if (!bar || !tasks) return;
    var wanted = {};
    tasks.forEach(function (t) { if (t.count > 0 || t.task === taskFilter) wanted[t.task] = t.task_no; });
    Array.prototype.forEach.call(bar.querySelectorAll('[data-task-link]'), function (a) {
      if (!(a.dataset.taskLink in wanted)) a.remove();
    });
    var empty = bar.querySelector('[data-tasks-empty]');
    Object.keys(wanted).map(Number).sort(function (a, b) { return wanted[a] - wanted[b]; }).forEach(function (task) {
      if (bar.querySelector('[data-task-link="' + task + '"]')) return;
      var a = document.createElement('a');
      a.className = 'btn btn-small btn-secondary'; a.dataset.taskLink = task;
      var base = liveUrl.split('?')[1] || '', params = new URLSearchParams(base);
      params.set('task', task);
      a.href = '?' + params.toString();
      a.setAttribute('aria-label', 'Задача ' + wanted[task]); a.title = 'Доски задачи ' + wanted[task] + ' у всех учеников';
      a.textContent = wanted[task];
      if (task === taskFilter) a.setAttribute('aria-current', 'page');
      /* по порядку номеров: перед первой кнопкой с большим номером, иначе перед подписью «пусто» */
      var next = Array.prototype.find.call(bar.querySelectorAll('[data-task-link]'), function (b) { return wanted[b.dataset.taskLink] > wanted[task]; });
      bar.insertBefore(a, next || empty);
    });
    if (empty) empty.hidden = !!bar.querySelector('[data-task-link]');
  }
  function apply(data) {
    syncTaskLinks(data.tasks);
    var seen = {};
    data.states.forEach(function (state, i) {
      seen[state.assignment] = true;
      var el = ensureCard(state);
      el.dataset.reviewUrl = state.review_url; el.dataset.student = state.student;
      el.querySelector('[data-board-state]').textContent = state.status_label;
      el.style.order = i;
    });
    Array.prototype.forEach.call(root.querySelectorAll('[data-board]'), function (el) {
      if (!seen[el.dataset.board]) el.remove();
    });
    (data.tasks || []).forEach(function (t) {
      var byTask = pagesOf[t.assignment] = pagesOf[t.assignment] || {};
      var entry = byTask[t.task] = byTask[t.task] || {task_no: t.task_no, canvas_url: t.canvas_url, count: 0};
      entry.count = Math.max(entry.count, t.count);
    });
    data.pages.forEach(function (page) {
      var byTask = pagesOf[page.assignment] = pagesOf[page.assignment] || {};
      var entry = byTask[page.task] = byTask[page.task] || {task_no: page.task_no, canvas_url: page.canvas_url, count: 0};
      entry.count = Math.max(entry.count, page.number);
      var current = latest[page.assignment];
      if (!current || page.updated >= current.updated) { latest[page.assignment] = page; paint(page); }
      if (open && open.assignment === page.assignment) {
        var node = dialog.querySelector('[data-canvas]');
        if (node && node.canvasWidget) node.canvasWidget.reload();
      }
    });
  }
  function tickAgo() {
    Array.prototype.forEach.call(root.querySelectorAll('[data-board][data-updated]'), function (el) {
      el.querySelector('[data-board-updated]').textContent = ago(el.dataset.updated);
    });
  }
  function poll() {
    if (busy || stopped || document.hidden) return;
    if (Date.now() - lastActivity > IDLE) { stop(); return; }
    busy = true;
    var url = liveUrl + (liveUrl.indexOf('?') >= 0 ? '&' : '?') + (since ? 'since=' + encodeURIComponent(since) : '');
    var headers = {'X-Requested-With': 'XMLHttpRequest'};
    if (etag) headers['If-None-Match'] = etag;
    fetch(url, {credentials: 'same-origin', headers: headers})
      .then(function (r) {
        if (r.status === 304) return null;
        if (!r.ok) throw new Error('HTTP ' + r.status);
        etag = r.headers.get('ETag');
        return r.json();
      })
      .then(function (data) {
        if (data && data.ok) { apply(data); since = data.since; }
        if (status) status.textContent = 'Доски обновляются каждые 5 секунд. Нажмите на доску, чтобы открыть её с инструментами.';
      })
      .catch(function () { if (status) status.textContent = 'Нет связи с сервером — попробуем снова через несколько секунд.'; })
      .finally(function () { busy = false; tickAgo(); });
  }
  function schedule() {
    clearInterval(timer);
    timer = setInterval(poll, dialog && dialog.open ? POLL_DIALOG : POLL);
  }
  function stop() {
    stopped = true; clearInterval(timer);
    if (!status) return;
    status.textContent = 'Обновление остановлено: полчаса без движения. ';
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn-small btn-secondary'; b.textContent = 'Продолжить';
    b.addEventListener('click', function () { stopped = false; lastActivity = Date.now(); poll(); schedule(); });
    status.appendChild(b);
  }
  ['pointermove', 'pointerdown', 'keydown'].forEach(function (name) {
    document.addEventListener(name, function () { lastActivity = Date.now(); }, {passive: true});
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });

  /* ---- диалог с виджетом учителя ---- */
  function mount(assignment, task) {
    var holder = dialog.querySelector('[data-dialog-canvas]');
    holder.innerHTML = '';
    var entry = pagesOf[assignment][task];
    var node = document.createElement('div');
    node.dataset.canvas = ''; node.dataset.role = 'teacher'; node.dataset.url = entry.canvas_url; node.dataset.pages = String(entry.count);
    node.dataset.always = '1';   /* тумблер «Показать доски» со страницы прогресса здесь не действует */
    node.id = 'boards-canvas-' + assignment + '-' + task;
    holder.appendChild(node);        /* canvas.js поднимет виджет через MutationObserver */
    open = {assignment: assignment, task: task};
    Array.prototype.forEach.call(dialog.querySelectorAll('[data-dialog-task]'), function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.dialogTask === String(task)));
    });
  }
  function openBoard(id) {
    var byTask = pagesOf[id], el = card(id);
    if (!byTask || !el) return;
    var tasks = Object.keys(byTask).sort(function (a, b) { return byTask[a].task_no - byTask[b].task_no; });
    dialog.querySelector('[data-dialog-title]').textContent = el.dataset.student;
    dialog.querySelector('[data-dialog-review]').href = el.dataset.reviewUrl;
    var bar = dialog.querySelector('[data-dialog-tasks]');
    bar.innerHTML = '';
    tasks.forEach(function (task) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'btn btn-small btn-secondary'; b.dataset.dialogTask = task;
      b.textContent = 'Задача ' + byTask[task].task_no + (byTask[task].count ? '' : ' — пусто');
      b.addEventListener('click', function () { mount(id, parseInt(task, 10)); });
      bar.appendChild(b);
    });
    /* При фильтре по задаче диалог открывается на ней — пустой, если доски нет:
       сервер добавляет такую задачу в tasks с count 0 */
    var first = taskFilter && byTask[taskFilter] ? taskFilter : latest[id] ? latest[id].task : parseInt(tasks[0], 10);
    mount(id, first);
    if (!dialog.open) dialog.showModal();
    schedule();
  }
  function closeBoard() {
    var node = dialog.querySelector('[data-canvas]');
    if (node && node.canvasWidget) node.canvasWidget.close();
    dialog.querySelector('[data-dialog-canvas]').innerHTML = '';
    open = null;
    if (dialog.open) dialog.close();
    schedule();
    poll();
  }
  root.addEventListener('click', function (e) {
    var copyBtn = e.target.closest('[data-board-copy]');
    if (copyBtn) {
      e.stopPropagation();
      var id = parseInt(copyBtn.closest('[data-board]').dataset.board, 10), page = latest[id], el0 = card(id);
      if (page) EgorCanvas.copy(page, (el0.dataset.student || 'доска') + ' — задача ' + page.task_no + '.png');
      return;
    }
    var el = e.target.closest('[data-board]');
    if (el) openBoard(parseInt(el.dataset.board, 10));
  });
  root.addEventListener('keydown', function (e) {
    var el = e.target.closest('[data-board]');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openBoard(parseInt(el.dataset.board, 10)); }
  });
  dialog.querySelector('[data-dialog-close]').addEventListener('click', closeBoard);
  dialog.addEventListener('cancel', function (e) { e.preventDefault(); closeBoard(); });
  dialog.addEventListener('click', function (e) { if (e.target === dialog) closeBoard(); });

  poll();
  schedule();
  setInterval(tickAgo, 15000);
})();
