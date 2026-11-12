/* Заглушка самостоятельной «Работа уже открыта на другом устройстве»
   (Run.lock_device, independentworks/devices.py).

   Решает сервер: чужому устройству страница приходит без заданий, ответы
   оттуда не принимаются. Скрипт только следит за переменами, опрашивая
   файл-версию попытки (статика, без Django): учитель переключил доступ на
   другое устройство — работа здесь закрывается заглушкой на месте, без
   перезагрузки, иначе учитель тут же увидел бы «попытку входа» отсюда;
   доступ вернули или блокировку выключили — страница перезагружается и
   приходит с заданиями. */
(function () {
  'use strict';
  const stub = document.querySelector('[data-iw-device]');
  if (!stub) return;
  const column = document.querySelector('.student-column');
  const watch = window.EgorLiveFile ? EgorLiveFile.watch(stub) : null;
  let busy = false, ticks = 0;

  function show() {
    stub.hidden = false;
    if (column) column.inert = true;
    // Фокус — на заглушку: экранный диктор прочтёт её, Tab не уйдёт под неё
    stub.focus();
  }
  async function check(force) {
    if (document.hidden || busy) return;
    busy = true;
    try {
      if (!force && watch && !(await watch.changed())) return;
      const response = await fetch(stub.dataset.iwDevice, {cache: 'no-store', headers: {'X-Requested-With': 'XMLHttpRequest'}});
      if (!response.ok) throw new Error(response.status);
      if (watch) watch.ack();
      const result = await response.json();
      if (result.foreign) { if (stub.hidden) show(); }
      // Пустили обратно или время работы вышло — страницу отдаст сервер
      else if (!stub.hidden) location.reload();
    } catch (_) { /* повторим при следующем опросе */ }
    finally { busy = false; }
  }
  setInterval(() => {
    // Под заглушкой раз в полминуты спрашиваем сервер и без перемен в файле:
    // конец работы по времени файл-версию не трогает
    ticks += 1;
    check(!stub.hidden && ticks % 6 === 0);
  }, 5000);
  // Ответ или фото отклонены с 403 — узнать, не закрыта ли работа здесь
  document.addEventListener('iw:device', () => check(true));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(false); });
  if (!stub.hidden) show();
})();
