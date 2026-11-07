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
  /* Файл-версия листка (data-live-file): пока он не менялся, boards_live не дёргаем. */
  var watch = window.EgorLiveFile ? EgorLiveFile.watch(root) : null;
  var latest = {};          /* assignment → последняя страница (payload) */
  var COPY_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var pagesOf = {};         /* assignment → {task: {task_no, canvas_url, count}} */
  var open = null;          /* {assignment, task} открытого диалога */
  /* Блок «Задание · ответ ученика» над доской: фрагмент с сервера. Развёрнут
     ли он (и «Ответ» в нём) — помним, пока открыта страница: учитель развернул
     у одного ученика — у следующего тоже развёрнут. answerVersions — версии
     ответов из живого опроса: блок перезагружается, только если ответ сменился. */
  var peekUrl = root.dataset.peekUrl || '';
  var peekState = {open: false, reference: false}, peekShown = null, peekSeq = 0, answerVersions = {};

  function card(id) { return root.querySelector('[data-board="' + id + '"]'); }
  /* «пишет сейчас» — доска менялась за последние LIVE мс (макет E_Boards) */
  var LIVE = 90 * 1000, IDLE_MARK = 15 * 60 * 1000;
  function ago(iso) {
    var s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (s * 1000 < LIVE) return 'пишет сейчас';
    if (s < 3600) return Math.max(1, Math.round(s / 60)) + ' мин назад';
    return new Date(iso).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
  }
  function activity(iso) {
    var ms = Date.now() - new Date(iso).getTime();
    return ms < LIVE ? 'live' : ms < IDLE_MARK ? 'idle' : 'old';
  }
  function setMark(el, state) {
    var mark = el.querySelector('[data-board-mark]');
    if (!mark) return;
    mark.dataset.mark = state.mark || '';
    mark.textContent = state.mark || '';
    if (state.mark_sub) { var sub = document.createElement('sub'); sub.textContent = state.mark_sub; mark.appendChild(sub); }
  }
  function liveCount() {
    var cards = root.querySelectorAll('[data-board]'), n = 0;
    Array.prototype.forEach.call(cards, function (el) { if (el.dataset.updated && activity(el.dataset.updated) === 'live') n++; });
    return 'Обновляются каждые 5 секунд; пишут сейчас ' + n + ' из ' + cards.length;
  }
  function setStatus(text) {
    if (!status) return;
    status.textContent = text;
    var dot = document.createElement('span');
    dot.className = 'bd-live-dot'; dot.setAttribute('aria-hidden', 'true');
    status.insertBefore(dot, status.firstChild);
  }
  function ensureCard(state) {
    var el = card(state.assignment);
    if (el) return el;
    el = document.createElement('article');
    el.className = 'board-card'; el.dataset.board = state.assignment; el.tabIndex = 0; el.setAttribute('role', 'button');
    el.className = 'board-card bd-card';
    el.innerHTML = '<div class="bd-card-head"><strong class="board-name"></strong><span class="bd-mark" data-board-mark></span><span class="board-state" data-board-state hidden></span></div>'
      + '<canvas class="board-thumb" width="300" height="300" aria-hidden="true"></canvas>'
      + '<div class="bd-card-foot"><span class="bd-activity" data-activity="none" aria-hidden="true"></span><span data-board-updated>доски пока нет</span><span class="bd-page" data-board-task></span>'
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
    var dot = el.querySelector('[data-activity]');
    if (dot) dot.dataset.activity = activity(page.updated);
    var copyBtn = el.querySelector('[data-board-copy]');
    if (copyBtn) copyBtn.hidden = false;
    el.classList.add('board-fresh');
    setTimeout(function () { el.classList.remove('board-fresh'); }, 4000);
  }
  /* Кнопки задач над сеткой: пересобираются из tasks каждого ответа — новая
     первая доска по задаче добавляет кнопку, удаление последней — убирает */
  function syncTaskLinks(tasks) {
    var bar = document.querySelector('[data-boards-tasks]');
    /* Лента E_Boards (data-all-tasks) показывает все задачи листка — не пересобираем */
    if (!bar || !tasks || bar.hasAttribute('data-all-tasks')) return;
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
  /* ?open=<назначение>: диалог открывается сам после первого ответа опроса,
     когда известны доски ученика (карточку сервер ставит на экран всегда) */
  var pendingOpen = parseInt(root.dataset.open || '0', 10) || 0;
  function apply(data) {
    syncTaskLinks(data.tasks);
    answerVersions = {};
    (data.answers || []).forEach(function (a) { answerVersions[a.assignment + ':' + a.task] = a.version; });
    if (open && peekShown && peekShown.key === open.assignment + ':' + open.task
        && (answerVersions[peekShown.key] || '') !== peekShown.version) loadPeek(open.assignment, open.task);
    var seen = {};
    data.states.forEach(function (state, i) {
      seen[state.assignment] = true;
      var el = ensureCard(state);
      el.dataset.reviewUrl = state.review_url; el.dataset.student = state.student;
      el.querySelector('[data-board-state]').textContent = state.status_label;
      setMark(el, state);
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
    if (open) syncNav(open.assignment);
    if (pendingOpen) {
      var id = pendingOpen;
      pendingOpen = 0;
      openBoard(id, taskFilter);
    }
  }
  function tickAgo() {
    Array.prototype.forEach.call(root.querySelectorAll('[data-board][data-updated]'), function (el) {
      el.querySelector('[data-board-updated]').textContent = ago(el.dataset.updated);
      var dot = el.querySelector('[data-activity]');
      if (dot) dot.dataset.activity = activity(el.dataset.updated);
    });
  }
  function fetchLive() {
    var url = liveUrl + (liveUrl.indexOf('?') >= 0 ? '&' : '?') + (since ? 'since=' + encodeURIComponent(since) : '');
    var headers = {'X-Requested-With': 'XMLHttpRequest'};
    if (etag) headers['If-None-Match'] = etag;
    return fetch(url, {credentials: 'same-origin', headers: headers})
      .then(function (r) {
        if (r.status === 304) return null;
        if (!r.ok) throw new Error('HTTP ' + r.status);
        etag = r.headers.get('ETag');
        return r.json();
      })
      .then(function (data) {
        if (data && data.ok) { apply(data); since = data.since; }
        if (watch) watch.ack();
      });
  }
  function poll() {
    if (busy || stopped || document.hidden) return;
    if (Date.now() - lastActivity > IDLE) { stop(); return; }
    busy = true;
    (watch ? watch.changed() : Promise.resolve(true))
      .then(function (changed) { return changed ? fetchLive() : null; })
      .then(function () {
      })
      .catch(function () { if (status) status.textContent = 'Нет связи с сервером — попробуем снова через несколько секунд.'; busy = 'failed'; })
      .finally(function () { var failed = busy === 'failed'; busy = false; tickAgo(); if (!failed) setStatus(liveCount()); });
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

  /* ---- блок «Задание · ответ ученика» ---- */
  function peekHolder() { return dialog.querySelector('[data-dialog-peek]'); }
  function loadPeek(assignment, task) {
    var holder = peekHolder();
    if (!holder || !peekUrl) return;
    var seq = ++peekSeq, key = assignment + ':' + task;
    var url = peekUrl.replace('/0/task/0/', '/' + assignment + '/task/' + task + '/');
    fetch(url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (html) {
        if (seq !== peekSeq || !open || open.assignment + ':' + open.task !== key) return;
        /* Обновление того же ответа из живого опроса не сбрасывает прокрутку блока */
        var prev = peekShown && peekShown.key === key ? holder.querySelector('.boards-peek-body') : null;
        var top = prev ? prev.scrollTop : 0;
        holder.innerHTML = html;
        var details = holder.querySelector('[data-peek]'), reference = holder.querySelector('[data-peek-reference]');
        peekShown = {key: key, version: details ? details.dataset.version || '' : ''};
        if (details) {
          details.open = peekState.open;
          details.addEventListener('toggle', function () { peekState.open = details.open; });
        }
        if (reference) {
          reference.open = peekState.reference;
          reference.addEventListener('toggle', function () { peekState.reference = reference.open; });
        }
        if (window.renderMathContent) holder.querySelectorAll('.math-content').forEach(window.renderMathContent);
        var body = holder.querySelector('.boards-peek-body');
        if (body && top) body.scrollTop = top;
      })
      .catch(function () {
        if (seq !== peekSeq) return;
        peekShown = null;
        holder.innerHTML = '<p class="helptext">Не удалось загрузить условие и ответ — откройте задачу ещё раз.</p>';
      });
  }
  function clearPeek() {
    peekSeq++; peekShown = null;
    var holder = peekHolder();
    if (holder) holder.innerHTML = '';
  }

  /* ---- диалог с виджетом учителя ---- */
  function mount(assignment, task) {
    var holder = dialog.querySelector('[data-dialog-canvas]');
    /* Смена ученика или задачи: сначала дописать штрихи учителя на прежней доске */
    var prev = holder.querySelector('[data-canvas]');
    if (prev && prev.canvasWidget) prev.canvasWidget.close();
    holder.innerHTML = '';
    var entry = ensureEntry(assignment, task);
    var node = document.createElement('div');
    node.dataset.canvas = ''; node.dataset.role = 'teacher'; node.dataset.url = entry.canvas_url; node.dataset.pages = String(entry.count);
    node.dataset.always = '1';   /* тумблер «Показать доски» со страницы прогресса здесь не действует */
    node.id = 'boards-canvas-' + assignment + '-' + task;
    holder.appendChild(node);        /* canvas.js поднимет виджет через MutationObserver */
    var same = open && open.assignment === assignment && open.task === task;
    open = {assignment: assignment, task: task};
    Array.prototype.forEach.call(dialog.querySelectorAll('[data-dialog-task]'), function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.dialogTask === String(task)));
    });
    if (!same || !peekShown) { clearPeek(); loadPeek(assignment, task); }
    syncReview();
  }
  /* Номера задач листка (лента над сеткой): 1–9 в диалоге и пустые доски задач,
     по которым у ученика ещё нет страниц */
  var taskNo = {}, taskByNo = {};
  Array.prototype.forEach.call(document.querySelectorAll('[data-task-link]'), function (a) {
    var task = parseInt(a.dataset.taskLink, 10), no = parseInt(a.textContent, 10);
    if (task && no) { taskNo[task] = no; taskByNo[no] = task; }
  });
  var canvasUrl = root.dataset.canvasUrl || '';
  /* Запись задачи ученика для диалога; нет страниц — пустая доска (count 0),
     как сервер делает для выбранной в ?task= задачи */
  function ensureEntry(id, task) {
    var byTask = pagesOf[id] = pagesOf[id] || {};
    if (!byTask[task] && canvasUrl && taskNo[task]) {
      byTask[task] = {task_no: taskNo[task], count: 0,
                      canvas_url: canvasUrl.replace('/0/canvas/0/', '/' + id + '/canvas/' + task + '/')};
    }
    return byTask[task];
  }
  /* Карточки в текущем порядке сетки (style.order из живого опроса) */
  function orderedCards() {
    return Array.prototype.slice.call(root.querySelectorAll('[data-board]')).sort(function (a, b) {
      return (parseInt(a.style.order, 10) || 0) - (parseInt(b.style.order, 10) || 0);
    });
  }
  function neighbour(id, step) {
    var cards = orderedCards(), i = cards.indexOf(card(id));
    return i < 0 ? null : cards[i + step] || null;
  }
  function syncNav(id) {
    Array.prototype.forEach.call(dialog.querySelectorAll('[data-dialog-step]'), function (b) {
      var step = parseInt(b.dataset.dialogStep, 10), el = neighbour(id, step);
      var focused = document.activeElement === b;
      b.hidden = !el;
      if (el) {
        b.textContent = step < 0 ? '← ' + el.dataset.student : el.dataset.student + ' →';
        b.title = (step < 0 ? 'Предыдущий ученик' : 'Следующий ученик') + ' (' + (step < 0 ? '←' : '→') + ')';
      } else if (focused) dialog.querySelector('[data-dialog-close]').focus();  /* фокус не теряется на скрытой кнопке */
    });
  }
  /* Адрес страницы помнит открытую доску (?open=): перезагрузка открывает её же */
  function syncAddress(id) {
    if (!window.history || !history.replaceState) return;
    var url = new URL(location.href);
    if (id) url.searchParams.set('open', id); else url.searchParams.delete('open');
    history.replaceState(history.state, '', url.toString());
  }
  function openBoard(id, wanted) {
    var el = card(id);
    if (!el) return;
    /* Задача: запрошенная (соседний ученик, 1–9, ссылка), иначе выбранная в
       ленте, иначе последняя изменённая доска, иначе первая задача листка */
    var first = wanted || taskFilter || (latest[id] ? latest[id].task : 0);
    if (!first) {
      var own = Object.keys(pagesOf[id] || {});
      first = own.length ? parseInt(own.sort(function (a, b) { return pagesOf[id][a].task_no - pagesOf[id][b].task_no; })[0], 10)
                         : taskByNo[1];
    }
    if (!first || !ensureEntry(id, first)) return;
    var byTask = pagesOf[id];
    var tasks = Object.keys(byTask).sort(function (a, b) { return byTask[a].task_no - byTask[b].task_no; });
    dialog.querySelector('[data-dialog-title]').textContent = el.dataset.student || el.querySelector('.board-name').textContent;
    var bar = dialog.querySelector('[data-dialog-tasks]');
    bar.innerHTML = '';
    tasks.forEach(function (task) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'btn btn-small btn-secondary'; b.dataset.dialogTask = task;
      b.textContent = 'Задача ' + byTask[task].task_no + (byTask[task].count ? '' : ' — пусто');
      if (byTask[task].task_no <= 9) b.setAttribute('aria-keyshortcuts', String(byTask[task].task_no));
      b.addEventListener('click', function () { mount(id, parseInt(task, 10)); });
      bar.appendChild(b);
    });
    mount(id, first);
    syncNav(id);
    syncAddress(id);
    if (!dialog.open) dialog.showModal();
    schedule();
  }
  /* «Открыть проверку работы» — сразу к задаче открытой доски */
  function syncReview() {
    var el = open && card(open.assignment), link = dialog.querySelector('[data-dialog-review]');
    if (!el || !link) return;
    var entry = pagesOf[open.assignment] && pagesOf[open.assignment][open.task];
    link.href = (el.dataset.reviewUrl || '#') + (entry && entry.task_no ? '#task-' + entry.task_no : '');
  }
  /* Клавиши диалога: ←/→ — соседний ученик (та же задача), 1–9 — задача,
     Esc — закрыть (cancel ниже). Не мешаем доске: поля ввода, выделение
     на холсте (там стрелки двигают элементы) и сочетания с модификаторами. */
  dialog.addEventListener('keydown', function (e) {
    if (!open || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable || t.tagName === 'MATH-FIELD')) return;
    var node = dialog.querySelector('[data-canvas]'), widget = node && node.canvasWidget;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      if (widget && widget.selection && widget.selection.length) return;
      var el = neighbour(open.assignment, e.key === 'ArrowLeft' ? -1 : 1);
      if (!el) return;
      e.preventDefault();
      openBoard(parseInt(el.dataset.board, 10), open.task);
      return;
    }
    if (/^[1-9]$/.test(e.key) && !e.shiftKey) {
      var task = taskByNo[parseInt(e.key, 10)];
      if (!task) return;
      e.preventDefault();
      if (task !== open.task) openBoard(open.assignment, task);
    }
  });
  Array.prototype.forEach.call(dialog.querySelectorAll('[data-dialog-step]'), function (b) {
    b.addEventListener('click', function () {
      var el = open && neighbour(open.assignment, parseInt(b.dataset.dialogStep, 10));
      if (el) openBoard(parseInt(el.dataset.board, 10), open.task);
    });
  });
  function closeBoard() {
    var node = dialog.querySelector('[data-canvas]');
    if (node && node.canvasWidget) node.canvasWidget.close();
    dialog.querySelector('[data-dialog-canvas]').innerHTML = '';
    clearPeek();
    var last = open && card(open.assignment);
    open = null;
    syncAddress(null);
    if (dialog.open) dialog.close();
    /* Фокус — на карточку последнего просмотренного ученика (после ←/→ или
       открытия по ссылке прежнего фокуса на странице нет) */
    if (last) last.focus();
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
    /* Enter/Space на кнопке копирования — её собственный click, не открытие карточки */
    if (e.target.closest('[data-board-copy]')) return;
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
