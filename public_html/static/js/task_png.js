// Кнопка [data-task-png]: копирует условие задачи картинкой PNG в буфер обмена,
// чтобы вставить её на доску (Miro и т.п.). Условие — ближайший
// [data-task-png-root], а внутри него [data-task-png-content], если он есть.
// Копия условия рисуется на белом листе шириной не больше 600px (как строка
// на карточке самостоятельной), без ответов, масок и кнопок.
// Рендер DOM → PNG — modern-screenshot, грузится только при первом нажатии.
(function () {
  var LIB_URL = 'https://cdn.jsdelivr.net/npm/modern-screenshot@4.6.8/dist/index.js';
  // Всё, что не относится к самому условию: управление, ответы, маски, бейджи
  var SKIP = [
    'button', 'form', 'details', 'input', 'select', 'textarea', 'script', 'template',
    'object', '[hidden]', '.ws-answers', '.usage-badge', '[data-worksheet-mask]',
    '.ws-stars', '[data-task-png-skip]',
  ].join(',');
  var LETTERS = 'абвгдежзиклмнопрстуф';
  var libPromise = null;

  function loadLib() {
    if (window.modernScreenshot) return Promise.resolve(window.modernScreenshot);
    if (!libPromise) {
      libPromise = new Promise(function (resolve, reject) {
        var script = document.createElement('script');
        script.src = LIB_URL;
        script.onload = function () { resolve(window.modernScreenshot); };
        script.onerror = function () { libPromise = null; reject(new Error('lib')); };
        document.head.appendChild(script);
      });
    }
    return libPromise;
  }

  function buildSheet(button) {
    var root = button.closest('[data-task-png-root]');
    if (!root) return null;
    var source = root.querySelector('[data-task-png-content]') || root;
    var clone = source.cloneNode(true);
    // В карточке кандидата самостоятельной подпункты — внутри формы выбора,
    // которая ниже удаляется целиком: поднимаем их под текст условия.
    // При «Вся задача» на картинку идут все пункты, независимо от галочек.
    clone.querySelectorAll('form').forEach(function (form) {
      var lists = form.querySelectorAll('ol.subitems');
      if (!lists.length) return;
      var whole = form.querySelector('input[name=parts_mode][value=all]:checked');
      var text = clone.querySelector('.task-text');
      var parent = text ? text.parentNode : form.parentNode;
      var anchor = text ? text.nextSibling : form;
      lists.forEach(function (list) {
        if (whole) list.setAttribute('data-task-png-whole', '');
        parent.insertBefore(list, anchor);
      });
    });
    // В листке подпункты отмечаются галочками: на картинку — только выбранные
    // (cloneNode переносит и текущее состояние галочки)
    clone.querySelectorAll('ol.subitems:not([data-task-png-whole]) > li').forEach(function (li) {
      var box = li.querySelector('input[type=checkbox]');
      if (box && !box.checked) li.remove();
    });
    // Блоки только для картинки (скрыты на странице) — показываем в копии
    clone.querySelectorAll('[data-task-png-only]').forEach(function (el) { el.removeAttribute('hidden'); });
    clone.querySelectorAll(SKIP).forEach(function (el) { el.remove(); });
    // «а)», «б)» у подпунктов — CSS-счётчик в ::before, рендер его не вычисляет:
    // ставим метки текстом (после отбора, как в листке у ученика)
    clone.querySelectorAll('ol.subitems').forEach(function (list) {
      Array.prototype.forEach.call(list.children, function (li, index) {
        var marker = document.createElement('span');
        marker.className = 'task-png-marker';
        marker.textContent = (LETTERS[index] || '') + ')';
        li.insertBefore(marker, li.firstChild);
      });
    });
    clone.querySelectorAll('[id]').forEach(function (el) { el.removeAttribute('id'); });
    clone.removeAttribute('id');
    // Рамка и фон карточки-обёртки на картинке не нужны
    if (source === root) clone.removeAttribute('class');
    clone.querySelectorAll('img').forEach(function (img) { img.removeAttribute('loading'); });
    // Лист снимается целиком; внешняя обёртка только уводит его за экран
    var holder = document.createElement('div');
    holder.className = 'task-png-holder';
    var sheet = document.createElement('div');
    sheet.className = 'task-png-sheet';
    // Есть номер — подпункты и рисунки на линии текста, как в просмотре листка
    if (clone.querySelector('.ws-num')) sheet.classList.add('ws-view');
    sheet.appendChild(clone);
    holder.appendChild(sheet);
    document.body.appendChild(holder);
    return {holder: holder, sheet: sheet};
  }

  function render(parts) {
    var images = Array.prototype.slice.call(parts.sheet.querySelectorAll('img'));
    var ready = images.map(function (img) {
      // Не загрузившийся рисунок дал бы пустую рамку — убираем его
      return img.decode ? img.decode().catch(function () { img.remove(); }) : null;
    });
    return Promise.all([loadLib()].concat(ready)).then(function (result) {
      return result[0].domToBlob(parts.sheet, {scale: 2, type: 'image/png', backgroundColor: '#ffffff'});
    }).finally(function () {
      parts.holder.remove();
    });
  }

  function notify(ok, message) {
    if (window.EgorAutosave && window.EgorAutosave.showSaved) {
      window.EgorAutosave.showSaved(ok, message);
    }
  }

  // Без доступа к буферу (старый браузер, запрет) — скачиваем файл:
  // его тоже можно перетащить на доску
  function download(blob) {
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'task.png';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-task-png]');
    if (!button) return;
    event.preventDefault();
    var parts = buildSheet(button);
    if (!parts) return;
    button.disabled = true;
    var blobPromise = render(parts);
    // ClipboardItem получает промис сразу, в обработчике клика: иначе Safari
    // считает запись в буфер вызванной не пользователем
    var copied;
    if (navigator.clipboard && navigator.clipboard.write && window.ClipboardItem) {
      copied = navigator.clipboard.write([new ClipboardItem({'image/png': blobPromise})])
        .then(function () { notify(true, 'Условие скопировано картинкой ✓'); })
        .catch(function () {
          return blobPromise.then(function (blob) {
            download(blob);
            notify(true, 'Буфер недоступен — картинка скачана');
          });
        });
    } else {
      copied = blobPromise.then(function (blob) {
        download(blob);
        notify(true, 'Буфер недоступен — картинка скачана');
      });
    }
    copied.catch(function () {
      notify(false, 'Не удалось сделать картинку');
    }).finally(function () {
      button.disabled = false;
    });
  });
})();
