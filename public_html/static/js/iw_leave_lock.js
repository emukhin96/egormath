/* Заглушка самостоятельной «Вы ушли со страницы» (Run.lock_on_leave).

   Уход — страница скрыта (другая вкладка, приложение, свёрнутое окно) или
   окно без фокуса (другое окно рядом). Дольше LIMIT — задания закрываются,
   пока учитель не разблокирует их на странице прогресса; разблокировка
   разовая, следующий уход снова закрывает. О каждом долгом уходе страница
   сообщает серверу, а блокирует он, только если настройка включена: так её
   можно включить посреди работы без перезагрузки у ученика.

   Не уход: окно выбора фото (на телефоне — камера), ссылка работы в новой
   вкладке (PDF-иллюстрация без встроенного просмотра), подтверждение «Сдать
   работу?» (пока оно открыто, скрипты стоят) и перезагрузка страницы. Фото
   решения открываются просмотром на этой же странице, без новой вкладки.
   Уход совсем (другой адрес, закрытая вкладка) браузер запоминает и
   сравнивает с порогом при следующем открытии работы. */
(function () {
  'use strict';
  const lock = document.querySelector('[data-iw-lock]');
  if (!lock) return;
  const LIMIT = 2000;
  // Выбор фото или ссылка работы дольше этого — всё же уход: снимок не
  // делают минутами
  const EXCUSE_LIMIT = 180000;
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  const column = document.querySelector('.student-column');
  const storageKey = 'iw-left-' + lock.dataset.attempt;
  // Заблокированная попытка приходит с сервера без заданий: снять заглушку
  // мало, после разблокировки страница перезагружается
  const bare = !lock.hidden;
  let awaySince = null, excused = false, reported = false, timer = null;
  // excuseAt — когда ученик открыл окно выбора фото или ссылку работы
  let blurred = false, excuseAt = -Infinity;
  // pending — блокировка ещё не дошла до сервера (сбой сети): опрос повторит её
  let pending = false, busy = false, polling = null, watch = null;

  function away() { return document.hidden || blurred; }
  function enabled() { return lock.dataset.enabled === '1'; }

  function show(locked) {
    const shown = !lock.hidden;
    lock.hidden = !locked;
    if (column) column.inert = locked;
    // Фокус — на заглушку: экранный диктор прочтёт её, Tab не уйдёт под неё
    if (locked && !shown) lock.focus();
    if (locked && !polling) {
      watch = window.EgorLiveFile ? EgorLiveFile.watch(lock) : null;
      polling = setInterval(poll, 3000);
    } else if (!locked && polling) {
      clearInterval(polling);
      polling = null;
    }
  }
  function apply(result) {
    lock.dataset.enabled = result.enabled ? '1' : '0';
    if (result.finished || (bare && !result.locked)) location.reload();
    else show(result.locked);
  }
  async function report() {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(lock.dataset.iwLock, {method: 'POST', keepalive: true,
        headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'}});
      if (!response.ok) throw new Error(response.status);
      pending = false;
      apply(await response.json());
    } catch (_) { /* заглушка остаётся, опрос повторит */ }
    finally { busy = false; }
  }
  function lockNow() {
    // Настройка включена — заглушка сразу, не дожидаясь ответа сервера
    if (enabled()) show(true);
    pending = true;
    report();
  }
  async function poll() {
    if (document.hidden || busy) return;
    if (pending) return report();
    busy = true;
    try {
      if (watch && !(await watch.changed())) return;
      const response = await fetch(lock.dataset.iwLock, {cache: 'no-store', headers: {'X-Requested-With': 'XMLHttpRequest'}});
      if (!response.ok) throw new Error(response.status);
      if (watch) watch.ack();
      apply(await response.json());
    } catch (_) { /* повторим через 3 секунды */ }
    finally { busy = false; }
  }

  function leave() {
    if (awaySince !== null || !away()) return;
    awaySince = Date.now();
    excused = awaySince - excuseAt < 60000;
    reported = false;
    clearTimeout(timer);
    timer = setTimeout(expire, (excused ? EXCUSE_LIMIT : LIMIT) + 50);
  }
  // Ещё не вернулся, а время вышло — блокируем сразу: учитель видит это в
  // таблице, не дожидаясь возвращения (на телефоне таймер может и не сработать)
  function expire() {
    if (awaySince === null || !away() || reported) return;
    reported = true;
    lockNow();
  }
  function back() {
    if (awaySince === null || away()) return;
    clearTimeout(timer);
    if (!reported && Date.now() - awaySince >= (excused ? EXCUSE_LIMIT : LIMIT)) lockNow();
    awaySince = null;
    excuseAt = -Infinity;
    // Вернулся к заглушке — сразу узнать, не разблокировал ли учитель
    if (!lock.hidden) poll();
  }

  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.matches('input[type=file]')) { excuseAt = Date.now(); return; }
    const link = target.closest('a[target=_blank]');
    if (!link || !column || !column.contains(link)) return;
    // Своё фото — просмотром здесь же: новая вкладка скрыла бы работу (ревью #290)
    const photo = link.closest('.iw-photo') && link.querySelector('img');
    if (photo && window.EgorImageZoom) {
      event.preventDefault();
      EgorImageZoom.open(photo);
      return;
    }
    excuseAt = Date.now();
  }, true);
  document.addEventListener('cancel', event => {
    if (event.target instanceof Element && event.target.matches('input[type=file]') && awaySince === null) excuseAt = -Infinity;
  }, true);
  // Видимость — главный признак (на телефоне фокус окна ненадёжен); видимая
  // страница считается и вернувшей фокус
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return leave();
    blurred = false;
    back();
  });
  window.addEventListener('blur', event => {
    if (event.target !== window) return;
    // Фокус ушёл во фрейм внутри страницы — это не уход
    setTimeout(() => { if (!document.hasFocus()) { blurred = true; leave(); } }, 0);
  });
  window.addEventListener('focus', event => {
    if (event.target !== window) return;
    blurred = false;
    back();
  });
  window.addEventListener('pagehide', () => {
    try { localStorage.setItem(storageKey, String(awaySince ?? Date.now())); } catch (_) {}
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    try { localStorage.removeItem(storageKey); } catch (_) {}
    blurred = false;
    back();
  });
  // Сохранение ответа или фото отклонено: работа заблокирована в другой вкладке
  document.addEventListener('iw:locked', () => show(true));
  document.querySelector('.iw-head-back')?.addEventListener('click', event => {
    if (enabled() && !window.confirm('Если уйти со страницы, задания заблокируются, пока учитель их не разблокирует. Уйти?')) event.preventDefault();
  });
  // Перетащить фото из другого окна или скопировать его там — тоже уход:
  // подсказку об этом при включённой блокировке не показываем
  if (enabled()) document.querySelectorAll('[data-iw-photos-hint]').forEach(hint => { hint.hidden = true; });

  let left = null;
  try {
    left = Number(localStorage.getItem(storageKey)) || null;
    localStorage.removeItem(storageKey);
  } catch (_) {}
  const navigation = performance.getEntriesByType ? performance.getEntriesByType('navigation')[0] : null;
  if (bare) show(true);
  else if (left && navigation?.type !== 'reload' && Date.now() - left >= LIMIT) lockNow();
})();
