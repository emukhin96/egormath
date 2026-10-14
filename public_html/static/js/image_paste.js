/* Вставка картинки из буфера обмена во все поля загрузки изображений.

   Подключается один раз в base.html. Улучшает каждый input[type=file],
   чей accept допускает картинки (image/*, .png, .jpg…), или с атрибутом
   data-image-paste; data-image-paste="off" — не трогать поле.

   Рядом с полем появляется зона .paste-zone: кнопка «Вставить из буфера»,
   подсказка «или Ctrl+V / ⌘V», приём перетаскиваемого файла, миниатюра
   и имя выбранного файла с × «убрать». Файл попадает в input.files через
   DataTransfer, после чего поле получает обычное событие change — так
   срабатывают существующие обработчики (превью, автоотправка фото).

   Ctrl+V: картинка уходит в зону, где нажали «Вставить из буфера», или
   в пустое поле (зону) в фокусе; если фокус не в текстовом поле — ещё под курсором
   или с которым работали последним, но только пустое (не перезаписываем
   выбранный файл и сохранённую картинку строки без явного выбора);
   затем в поле, которое подскажет страница (EgorImagePaste.addResolver,
   например первое пустое поле формсета картинок), и, если фокус не в
   текстовом поле, в единственное пустое поле. Иначе — тост «Куда
   вставить?». Вставку текста не перехватываем.

   Атрибуты поля:
     data-image-paste-thumb="off" — не показывать миниатюру в зоне
       (у строки уже есть своё превью).
     data-image-paste-fallback="off" — класть файл только по явному выбору
       (фокус в поле/зоне или кнопка зоны), не по курсору, «последнему
       активному» или «единственному пустому»: для полей, которые
       отправляют форму сразу по change.

   API для загрузчиков без <input type=file>:
     EgorImagePaste.attach(element, onFile) — element становится зоной
       приёма (фокус/курсор/последний активный), onFile(file) получает
       вставленную или перетащенную картинку.
     EgorImagePaste.addResolver(fn) — fn(file) возвращает поле или зону
       для вставки, когда пользователь не указал её сам. */
(function () {
  'use strict';

  var IMAGE_EXT = /^\.(png|jpe?g|gif|webp|bmp|tiff?|heic|heif|avif)$/i;
  var MIME_EXT = {
    'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg',
    'image/gif': 'gif', 'image/webp': 'webp', 'image/bmp': 'bmp',
    'image/tiff': 'tiff', 'image/avif': 'avif', 'image/heic': 'heic',
  };
  var isMac = /Mac|iPhone|iPad/.test(
    (navigator.userAgentData && navigator.userAgentData.platform)
    || navigator.platform || navigator.userAgent);
  var KEYS = isMac ? '⌘V' : 'Ctrl+V';

  var targets = [];      // {input?, zone, onFile?}
  var hovered = null;    // цель под курсором
  var lastActive = null; // цель, с которой работали последней
  var armed = null;      // зона, где нажали «Вставить из буфера»
  var resolvers = [];

  // --- Какие поля улучшаем ---
  function acceptsImages(input) {
    var flag = input.getAttribute('data-image-paste');
    if (flag === 'off') return false;
    if (flag !== null) return true;
    var accept = (input.getAttribute('accept') || '').toLowerCase();
    if (!accept) return false;
    return accept.split(',').some(function (part) {
      part = part.trim();
      return part.indexOf('image/') === 0 || IMAGE_EXT.test(part);
    });
  }

  // Подходит ли конкретный файл под accept поля
  function fileAllowed(input, file) {
    if (!file || file.type.indexOf('image/') !== 0) return false;
    if (!input) return true;
    var accept = (input.getAttribute('accept') || '').toLowerCase().trim();
    if (!accept) return true;
    var type = file.type.toLowerCase();
    var ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    return accept.split(',').some(function (part) {
      part = part.trim();
      if (!part) return false;
      if (part === 'image/*') return true;
      if (part.charAt(0) === '.') {
        return part === ext || (part === '.jpg' && ext === '.jpeg')
          || (part === '.jpeg' && ext === '.jpg');
      }
      return part === type;
    });
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // Файл из буфера без имени (или «image.png») получает понятное имя
  function named(blob) {
    var type = (blob.type || 'image/png').toLowerCase();
    var ext = MIME_EXT[type] || type.split('/')[1] || 'png';
    var d = new Date();
    var name = 'paste-' + d.getFullYear() + pad(d.getMonth() + 1)
      + pad(d.getDate()) + '-' + pad(d.getHours()) + pad(d.getMinutes())
      + pad(d.getSeconds()) + '.' + ext;
    try {
      return new File([blob], name, {type: type, lastModified: d.getTime()});
    } catch (e) {
      blob.name = name;  // очень старые браузеры без конструктора File
      return blob;
    }
  }

  function isUsable(t) {
    if (!t.zone.isConnected) return false;
    if (t.input && (!t.input.isConnected || t.input.disabled)) return false;
    // Скрытая строка формсета или закрытый диалог — не цель
    return !t.zone.closest('[hidden]');
  }

  function isEmpty(t) {
    return !t.input || !(t.input.files && t.input.files.length);
  }

  function isVisible(t) {
    return t.zone.getClientRects().length > 0;
  }

  function findTarget(el) {
    if (!el || !el.nodeType) return null;
    for (var i = 0; i < targets.length; i += 1) {
      var t = targets[i];
      if (t.input === el || t.zone === el || t.zone.contains(el)
          || (t.label && t.label.contains(el))) {
        return t;
      }
    }
    return null;
  }

  // --- Отображение выбранного файла в зоне ---
  function render(t) {
    var input = t.input;
    if (!input) return;
    var files = input.files ? Array.prototype.slice.call(input.files) : [];
    var box = t.zone.querySelector('.paste-zone-file');
    var thumb = t.zone.querySelector('.paste-zone-thumb');
    var name = t.zone.querySelector('.paste-zone-name');
    if (t.thumbUrl) { URL.revokeObjectURL(t.thumbUrl); t.thumbUrl = null; }
    if (!files.length) {
      box.hidden = true;
      return;
    }
    var last = files[files.length - 1];
    name.textContent = files.length > 1
      ? files.length + ' файла(ов): ' + files.map(function (f) { return f.name; }).join(', ')
      : last.name;
    name.title = name.textContent;
    if (thumb) {
      if (last.type.indexOf('image/') === 0) {
        t.thumbUrl = URL.createObjectURL(last);
        thumb.src = t.thumbUrl;
        thumb.hidden = false;
      } else {
        thumb.hidden = true;
        thumb.removeAttribute('src');
      }
    }
    box.hidden = false;
  }

  function say(t, text) {
    var msg = t.zone.querySelector('.paste-zone-msg');
    if (!msg) return;
    msg.textContent = text || '';
    msg.hidden = !text;
  }

  function toast(ok, text) {
    if (window.EgorAutosave && window.EgorAutosave.showSaved) {
      window.EgorAutosave.showSaved(ok, text);
    }
  }

  // Поле внутри закрытого <details> — раскрываем, чтобы файл был виден
  function reveal(el) {
    for (var d = el.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) {
      d.open = true;
    }
  }

  // --- Запись файла в цель ---
  // files — один файл или массив: несколько перетащенных картинок
  // записываются разом и дают ОДНО событие change (иначе автоотправка
  // фото решения ушла бы по разу на каждый файл).
  // deliver не делает поле «последним активным»: иначе следующий Ctrl+V
  // затёр бы только что вставленную картинку вместо новой строки формсета.
  function deliver(t, files, quiet) {
    armed = null;
    files = [].concat(files);
    if (t.onFile) {
      files.forEach(function (f) { t.onFile(f); });
      return true;
    }
    var input = t.input;
    var ok = files.filter(function (f) { return fileAllowed(input, f); });
    if (!ok.length) {
      say(t, 'Этот формат сюда не подходит.');
      toast(false, 'Формат картинки не подходит для этого поля');
      return false;
    }
    if (!input.multiple) ok = ok.slice(0, 1);
    var dt;
    try { dt = new DataTransfer(); } catch (e) { dt = null; }
    if (!dt) {
      say(t, 'Браузер не умеет вставлять файл — выберите его кнопкой.');
      return false;
    }
    if (input.multiple && input.files) {
      Array.prototype.forEach.call(input.files, function (f) { dt.items.add(f); });
    }
    ok.forEach(function (f) { dt.items.add(f); });
    input.files = dt.files;
    say(t, ok.length < files.length ? 'Часть файлов пропущена: формат не подходит.' : '');
    reveal(t.zone);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
    if (!quiet) toast(true, 'Картинка вставлена');
    return true;
  }


  function clear(t) {
    if (!t.input) return;
    t.input.value = '';
    say(t, '');
    t.input.dispatchEvent(new Event('input', {bubbles: true}));
    t.input.dispatchEvent(new Event('change', {bubbles: true}));
  }

  // --- Кнопка «Вставить из буфера»: Async Clipboard API ---
  function readClipboard(t) {
    lastActive = t;
    armed = t;  // кнопка могла не получить фокус (Safari, Firefox на macOS)
    var hint = 'Нажмите ' + KEYS + ', чтобы вставить картинку сюда.';
    if (!navigator.clipboard || !navigator.clipboard.read) {
      say(t, hint);
      return;
    }
    navigator.clipboard.read().then(function (items) {
      for (var i = 0; i < items.length; i += 1) {
        var types = items[i].types || [];
        for (var j = 0; j < types.length; j += 1) {
          if (types[j].indexOf('image/') === 0) {
            return items[i].getType(types[j]);
          }
        }
      }
      return null;
    }).then(function (blob) {
      if (!blob) {
        say(t, 'В буфере нет картинки. Скопируйте её и нажмите ' + KEYS + '.');
        return;
      }
      deliver(t, named(blob), true);
    }).catch(function () {
      say(t, hint);
    });
  }

  // --- Разметка зоны ---
  function buildZone(input) {
    var zone = document.createElement('div');
    zone.className = 'paste-zone';
    zone.setAttribute('data-paste-zone', '');
    var withThumb = input.getAttribute('data-image-paste-thumb') !== 'off';
    zone.innerHTML =
      '<button type="button" class="btn btn-secondary btn-small paste-zone-btn">'
      + 'Вставить из буфера</button>'
      + '<span class="paste-zone-hint">или ' + KEYS + ', или перетащите файл</span>'
      + '<span class="paste-zone-file" hidden>'
      + (withThumb ? '<img class="paste-zone-thumb" alt="" hidden>' : '')
      + '<span class="paste-zone-name"></span>'
      + '<button type="button" class="icon-btn paste-zone-clear" title="Убрать файл"'
      + ' aria-label="Убрать файл">×</button></span>'
      + '<span class="paste-zone-msg" role="status" hidden></span>';
    return zone;
  }

  function bindZone(t) {
    var zone = t.zone;
    zone.addEventListener('mouseenter', function () { hovered = t; });
    zone.addEventListener('mouseleave', function () { if (hovered === t) hovered = null; });
    zone.addEventListener('focusin', function () { lastActive = t; });
    zone.addEventListener('dragover', function (e) {
      if (!e.dataTransfer || [].indexOf.call(e.dataTransfer.types || [], 'Files') === -1) return;
      e.preventDefault();
      zone.classList.add('is-dragover');
    });
    zone.addEventListener('dragleave', function (e) {
      if (!zone.contains(e.relatedTarget)) zone.classList.remove('is-dragover');
    });
    zone.addEventListener('drop', function (e) {
      zone.classList.remove('is-dragover');
      var files = e.dataTransfer ? e.dataTransfer.files : null;
      if (!files || !files.length) return;
      e.preventDefault();
      var list = Array.prototype.filter.call(files, function (f) {
        return f.type.indexOf('image/') === 0;
      });
      if (!list.length) { say(t, 'Перетащите файл картинки.'); return; }
      deliver(t, list, true);
    });
    var btn = zone.querySelector('.paste-zone-btn');
    if (btn) btn.addEventListener('click', function () { readClipboard(t); });
    var x = zone.querySelector('.paste-zone-clear');
    if (x) x.addEventListener('click', function () { clear(t); });
  }

  function enhance(input) {
    if (input.dataset.imagePasteReady || !acceptsImages(input)) return;
    // Поле внутри <template> не улучшаем — его копия придёт в DOM позже
    if (input.closest('template')) return;
    input.dataset.imagePasteReady = '1';
    var zone = buildZone(input);
    // Поле внутри <label> (кнопка-«Фото решения»): зону ставим после
    // метки, иначе клик по нашим кнопкам открывал бы выбор файла.
    var label = input.closest('label');
    var anchor = label || input;
    anchor.insertAdjacentElement('afterend', zone);
    var t = {input: input, zone: zone, label: label};
    targets.push(t);
    bindZone(t);
    input.addEventListener('change', function () { render(t); });
    input.addEventListener('focus', function () { lastActive = t; });
    if (label) {
      label.addEventListener('mouseenter', function () { hovered = t; });
      label.addEventListener('mouseleave', function () { if (hovered === t) hovered = null; });
    }
    render(t);
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.matches && root.matches('input[type=file]')) enhance(root);
    root.querySelectorAll('input[type=file]').forEach(enhance);
  }

  function prune() {
    targets = targets.filter(function (t) { return t.zone.isConnected; });
    if (hovered && !hovered.zone.isConnected) hovered = null;
    if (lastActive && !lastActive.zone.isConnected) lastActive = null;
    if (armed && !armed.zone.isConnected) armed = null;
  }

  // --- Куда вставлять по Ctrl+V ---
  function isTextField(el) {
    if (!el || el === document.body) return false;
    if (el.isContentEditable) return true;
    var tag = el.tagName;
    if (tag === 'TEXTAREA' || tag === 'MATH-FIELD') return true;
    if (tag === 'INPUT') {
      return !/^(file|checkbox|radio|button|submit|reset|image|range|color|hidden)$/i.test(el.type);
    }
    return false;
  }

  // Поле с автоотправкой (data-image-paste-fallback="off") принимает
  // файл только по явному выбору: фокус в поле/зоне или нажатая кнопка
  // «Вставить из буфера» этой зоны.
  function explicitOnly(t) {
    return t.input && t.input.getAttribute('data-image-paste-fallback') === 'off';
  }

  // Строка формсета с уже сохранённым файлом (заполнен скрытый
  // «<префикс>-N-id»): наведение курсора не должно молча заменить его.
  function hasSavedFile(t) {
    var input = t.input;
    var m = input && input.name && input.name.match(/^(.*-\d+)-[^-]+$/);
    if (!m || !input.form) return false;
    var id = input.form.elements[m[1] + '-id'];
    return !!(id && id.value);
  }

  function implicitOk(t) {
    return isUsable(t) && !explicitOnly(t) && !hasSavedFile(t)
      && (isEmpty(t) || (t.input && t.input.multiple));
  }

  function resolveTarget(file) {
    prune();
    var focus = document.activeElement;
    // «Вставить из буфера» не смогла прочитать буфер и попросила Ctrl+V —
    // это явный выбор, даже если в поле уже есть файл.
    if (armed && isUsable(armed)) return armed;
    // Фокус в зоне/поле — тоже выбор, но фокус остаётся на кнопке и после
    // вставки: следующий Ctrl+V не должен затереть только что вставленное,
    // поэтому заполненное поле (без multiple) пропускаем — в форме задачи
    // картинка уйдёт в новую строку. Заменить файл — кнопкой или ×.
    var active = findTarget(focus);
    if (active && isUsable(active)
        && (isEmpty(active) || (active.input && active.input.multiple))) return active;
    // Человек печатает в текстовом поле вне зон: курсор мог случайно
    // остаться над чужой зоной, а «последнее активное» — устареть.
    // Тогда решают только подсказки страницы (формсет картинок задачи).
    var typing = isTextField(focus);
    // Без явного выбора заполненное поле не перезаписываем: ни уже
    // выбранный/вставленный файл, ни сохранённую картинку строки формсета
    // (поле с multiple не перезаписывается, а дополняется — его можно).
    if (!typing) {
      if (hovered && implicitOk(hovered)) return hovered;
      if (lastActive && implicitOk(lastActive)) return lastActive;
    }
    for (var i = 0; i < resolvers.length; i += 1) {
      var got = resolvers[i](file);
      var t = got && (findTarget(got) || null);
      if (!t && got && got.matches && got.matches('input[type=file]')) {
        enhance(got);
        t = findTarget(got);
      }
      if (t && isUsable(t)) return t;
    }
    // Запасная ветка «единственное пустое поле» — только когда человек не
    // печатает (скриншот, вставленный в ответ, не должен молча стать
    // файлом) и только для полей без автоотправки.
    if (typing) return null;
    var empty = targets.filter(function (t) {
      return t.input && isUsable(t) && isVisible(t) && isEmpty(t)
        && !explicitOnly(t);
    });
    return empty.length === 1 ? empty[0] : null;
  }


  function clipboardImage(data) {
    var items = data.items || [];
    for (var i = 0; i < items.length; i += 1) {
      if (items[i].kind === 'file' && items[i].type.indexOf('image/') === 0) {
        var f = items[i].getAsFile();
        if (f) return f;
      }
    }
    var files = data.files || [];
    for (var j = 0; j < files.length; j += 1) {
      if (files[j].type.indexOf('image/') === 0) return files[j];
    }
    return null;
  }

  function clipboardHasText(data) {
    var types = Array.prototype.slice.call(data.types || []);
    return types.indexOf('text/plain') !== -1 || types.indexOf('text/html') !== -1;
  }

  document.addEventListener('paste', function (e) {
    if (e.defaultPrevented || !e.clipboardData) return;
    var file = clipboardImage(e.clipboardData);
    if (!file) return;  // текст — не наше дело
    var focus = document.activeElement;
    // Фокус в текстовом поле и в буфере есть текст (например, копия
    // картинки со страницы приносит и HTML) — пусть вставляется текст.
    if (isTextField(focus) && !findTarget(focus) && clipboardHasText(e.clipboardData)) return;
    var t = resolveTarget(file);
    if (!t) {
      var visible = targets.some(function (x) { return isUsable(x) && isVisible(x); });
      if (visible) {
        toast(false, 'Куда вставить? Нажмите «Вставить из буфера» у нужного поля');
      }
      return;
    }
    e.preventDefault();
    var explicit = t === hovered || t === armed || t === findTarget(focus);
    var name = file.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(file.name) ? file : named(file);
    deliver(t, name, explicit);
  });

  // Ушли печатать в другое текстовое поле — «последнее активное» поле
  // загрузки больше не считается выбранным: иначе скриншот, вставленный
  // в ответ к задаче 5, уехал бы фотографией к задаче 3.
  document.addEventListener('focusin', function (e) {
    if (isTextField(e.target) && !findTarget(e.target)) {
      lastActive = null;
      armed = null;
    }
  });

  // --- API ---
  function attach(element, onFile) {
    var existing = findTarget(element);
    if (existing) { existing.onFile = onFile; return existing; }
    var t = {zone: element, onFile: onFile};
    targets.push(t);
    element.setAttribute('data-paste-zone', '');
    bindZone(t);
    return t;
  }

  function addResolver(fn) { resolvers.push(fn); }

  window.EgorImagePaste = {
    attach: attach,
    addResolver: addResolver,
    enhance: enhance,
    scan: scan,
  };

  function init() {
    scan(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        Array.prototype.forEach.call(r.addedNodes, function (node) {
          if (node.nodeType === 1) scan(node);
        });
      });
    }).observe(document.body, {childList: true, subtree: true});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
