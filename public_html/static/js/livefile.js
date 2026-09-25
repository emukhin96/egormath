/* Файлы-версии живых страниц (см. livefile/files.py).

   Страница с живым обновлением сначала спрашивает крошечный статический
   файл `data-live-file` — его отдаёт веб-сервер без запуска Django — и
   идёт за настоящими данными только когда содержимое файла изменилось.
   Нет файла или ошибка сети — работаем по-старому, опрашивая данные.

   var watch = EgorLiveFile.watch(element);   // element с data-live-file или URL
   if (await watch.changed()) { ...перезапросить данные...; watch.ack(); } */
(function () {
  'use strict';

  function Watch(url) { this.url = url || ''; this.seen = null; this.pending = null; }

  /* true — данные надо перезапросить (версия изменилась, файла нет или
     ошибка), false — с прошлого удачного обновления ничего не менялось. */
  Watch.prototype.changed = function () {
    var self = this;
    if (!this.url) return Promise.resolve(true);
    return fetch(this.url, {cache: 'no-store', credentials: 'same-origin'})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (text) { self.pending = text; return text !== self.seen; })
      .catch(function () { self.pending = null; return true; });
  };

  /* Данные перезапрошены успешно — эту версию считаем увиденной. */
  Watch.prototype.ack = function () { if (this.pending !== null) this.seen = this.pending; };

  window.EgorLiveFile = {
    watch: function (source) {
      var url = source && source.dataset ? source.dataset.liveFile : source;
      return new Watch(url);
    },
  };
})();
