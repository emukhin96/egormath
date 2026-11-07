/* Логин и пароль ученика — сразу в буфер обмена (ответ Егора к U1, 07.11).

   Формы с data-credentials-copy (создание ученика, сброс пароля) уходят
   запросом X-Requested-With, сервер отвечает JSON с логином и паролем.
   Запись в буфер запускается синхронно из отправки формы через
   ClipboardItem с обещанием — так Safari и Chrome считают её действием
   пользователя, хотя текст приходит позже. Затем страница перезагружается:
   тост «скопированы» — после перезагрузки, плашка с данными над списком
   остаётся запасным путём, если браузер не дал скопировать. */
(function () {
  'use strict';

  var FLAG = 'egor-credentials-copied';

  function text(data) {
    return 'Логин: ' + data.username + '\nПароль: ' + data.password;
  }

  function copyFrom(promise) {
    // ClipboardItem с обещанием — запись разрешена, пока длится действие
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      try {
        var item = new ClipboardItem({
          'text/plain': promise.then(function (data) {
            if (!data || !data.ok) throw new Error('no credentials');
            return new Blob([text(data)], {type: 'text/plain'});
          }),
        });
        return navigator.clipboard.write([item]);
      } catch (e) { /* старый ClipboardItem без обещаний — ниже */ }
    }
    return promise.then(function (data) {
      if (!data || !data.ok) throw new Error('no credentials');
      return navigator.clipboard.writeText(text(data));
    });
  }

  document.addEventListener('submit', function (event) {
    var form = event.target.closest('form[data-credentials-copy]');
    if (!form || event.defaultPrevented || !window.fetch) return;
    event.preventDefault();
    var request = fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      credentials: 'same-origin',
    }).then(function (r) { return r.json(); });
    var data = null;
    var answer = request.then(function (d) { data = d; return d; });
    var copied = copyFrom(answer).then(function () { return true; }, function () { return false; });
    Promise.all([answer.catch(function () { return null; }), copied]).then(function (res) {
      if (!res[0] || !res[0].ok) {
        // Ошибки формы — обычной отправкой: окно откроется с подсказками
        form.removeAttribute('data-credentials-copy');
        form.submit();
        return;
      }
      try { if (res[1]) sessionStorage.setItem(FLAG, data.username); } catch (e) { /* без хранилища — без тоста */ }
      window.location.reload();
    });
  });

  // После перезагрузки — тост и отметка у плашки
  document.addEventListener('DOMContentLoaded', function () {
    var name = null;
    try { name = sessionStorage.getItem(FLAG); sessionStorage.removeItem(FLAG); } catch (e) { /* нет хранилища */ }
    if (!name) return;
    // После тоста сервера («Ученик создан», «Пароль сброшен»), чтобы не перебить его
    setTimeout(function () {
      if (window.EgorAutosave && EgorAutosave.showSaved) {
        EgorAutosave.showSaved(true, 'Логин и пароль скопированы в буфер обмена');
      }
    }, 1700);
    var note = document.querySelector('[data-credentials-note]');
    if (note) note.hidden = false;
  });
})();
