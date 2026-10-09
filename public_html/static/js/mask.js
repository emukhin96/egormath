/* Поведение контролов маски ответа на странице ученика (разметка —
   _mask.html, серверная). Значения слотов уходят обычным автосохранением
   формы (autosave.js, событие change). Math-field зеркалится здесь же
   в скрытое поле; для строгих форматов техническая запись MathLive
   приводится к формату, который проверяет сервер.

   1. Слот «множество»: флажок «решений нет» очищает и блокирует поле чисел
      (сервер при флажке пишет ∅, что бы ни было в поле).
   2. Слот «порядок»: выбор элемента на одном месте снимает его с других мест,
      чтобы один элемент не стоял дважды (селекты — вариант без JS).
   3. Слот «порядок» с JS: селекты прячутся, элементы списка можно тащить
      мышью (HTML5 drag-and-drop) или переставлять кнопками ▲/▼ (телефон,
      клавиатура); порядок списка записывается в те же селекты, так что
      сервер и автосохранение ничего не замечают. */
(function () {
  'use strict';

  function enhanceOrderSlot(slot) {
    var list = slot.querySelector('.mask-order-items');
    var selects = Array.prototype.slice.call(slot.querySelectorAll('.mask-order-select'));
    if (!list || !selects.length || slot.dataset.enhanced) return;
    slot.dataset.enhanced = '1';
    var positions = slot.querySelector('.mask-order-positions');
    if (positions) positions.hidden = true;
    slot.classList.add('mask-order-dnd');

    var items = Array.prototype.slice.call(list.children);
    /* Сохранённый ответ — расставить элементы по нему; иначе как показал сервер */
    var saved = selects.map(function (s) { return s.value; });
    if (saved.every(Boolean) && new Set(saved).size === items.length) {
      saved.forEach(function (idx) {
        var li = items.filter(function (el) { return el.dataset.index === idx; })[0];
        if (li) list.appendChild(li);
      });
    }

    /* write — записать порядок в селекты и запустить автосохранение. Пока
       ученик ничего не трогал, селекты остаются пустыми: показанный
       перемешанный порядок — не ответ. */
    function sync(write) {
      var lis = Array.prototype.slice.call(list.children);
      lis.forEach(function (li, k) {
        var num = li.querySelector('.mask-order-num');
        if (num) num.textContent = (k + 1) + '.';
        li.querySelector('[data-move=up]').disabled = k === 0;
        li.querySelector('[data-move=down]').disabled = k === lis.length - 1;
        if (write && selects[k]) selects[k].value = li.dataset.index;
      });
      if (write) selects[selects.length - 1].dispatchEvent(new Event('change', {bubbles: true}));
    }

    function move(li, dir) {
      var sibling = dir < 0 ? li.previousElementSibling : li.nextElementSibling;
      if (!sibling) return;
      if (dir < 0) list.insertBefore(li, sibling); else list.insertBefore(sibling, li);
      sync(true);
      li.querySelector('[data-move=' + (dir < 0 ? 'up' : 'down') + ']').focus();
    }

    items.forEach(function (li) {
      li.draggable = true;
      li.classList.add('mask-order-item');
      var handle = document.createElement('span');
      handle.className = 'mask-order-handle';
      handle.textContent = '⋮⋮';
      handle.title = 'Перетащите, чтобы поменять порядок';
      li.insertBefore(handle, li.firstChild);
      var tools = document.createElement('span');
      tools.className = 'mask-order-tools';
      [['up', '▲', 'Выше'], ['down', '▼', 'Ниже']].forEach(function (b) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'icon-btn mask-order-move';
        btn.dataset.move = b[0];
        btn.textContent = b[1];
        btn.title = b[2];
        btn.setAttribute('aria-label', b[2]);
        btn.addEventListener('click', function () { move(li, b[0] === 'up' ? -1 : 1); });
        tools.appendChild(btn);
      });
      li.appendChild(tools);

      li.addEventListener('dragstart', function (e) {
        dragging = li;
        li.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', li.dataset.index);
      });
      li.addEventListener('dragend', finish);
    });

    var dragging = null;
    /* drop приходит раньше dragend и надёжнее (dragend теряется, если
       элемент перерисован) — завершаем по первому из них */
    function finish() {
      if (!dragging) return;
      dragging.classList.remove('dragging');
      dragging = null;
      sync(true);
    }
    list.addEventListener('dragover', function (e) {
      if (!dragging) return;
      e.preventDefault();
      var over = e.target.closest('li');
      if (!over || over === dragging) return;
      var rect = over.getBoundingClientRect();
      var after = e.clientY > rect.top + rect.height / 2;
      list.insertBefore(dragging, after ? over.nextSibling : over);
    });
    list.addEventListener('drop', function (e) { e.preventDefault(); finish(); });

    sync(false);
  }

  function bindSetSlots(root) {
    root.querySelectorAll('[data-mask-none]').forEach(function (box) {
      var wrap = box.closest('.mask-set');
      var input = wrap && wrap.querySelector('.mask-set-input');
      if (!input || box.dataset.bound) return;
      box.dataset.bound = '1';
      function sync() {
        input.disabled = box.checked;
        if (box.checked) input.value = '';
      }
      box.addEventListener('change', sync);
      sync();
    });
  }

  function bindOrderSlots(root) {
    root.querySelectorAll('[data-mask-order]').forEach(function (slot) {
      if (slot.dataset.bound) return;
      slot.dataset.bound = '1';
      var selects = slot.querySelectorAll('select');
      selects.forEach(function (sel) {
        /* Слушатель на самом select срабатывает раньше document-уровневого
           автосохранения, так что очищенный дубль попадёт в тот же запрос */
        sel.addEventListener('change', function () {
          if (!sel.value) return;
          selects.forEach(function (other) {
            if (other !== sel && other.value === sel.value) other.value = '';
          });
        });
      });
    });
  }

  function mirrorValue(field) {
    var value = field.value || '';
    if (!field.dataset.maskFormat) return value;
    return value.replace(/\{,\}/g, ',').replace(/\\colon\s*/g, ':').trim();
  }

  /* Формат бланка (digits/decimal/ratio): та же проверка, что
     formats.wrong_format на сервере, — подсказка появляется при вводе,
     до нажатия «Проверить» и списания попытки. */
  var FORMATS = {
    digits: /^[0-9]+$/,
    decimal: /^-?[0-9]+(?:,[0-9]+)?$/,
  };

  function wrongFormat(field, value) {
    var kind = field.dataset.maskFormat;
    if (!value) return false;
    if (FORMATS[kind]) return !FORMATS[kind].test(value);
    if (kind === 'ratio' || kind === 'proportion') return value.indexOf(':') < 0 && !field.dataset.maskQuotient;
    return false;
  }

  function showFormatHint(field, wrap, value) {
    var hint = wrap.querySelector('[data-mask-format-hint]');
    if (!hint) return;
    var bad = wrongFormat(field, value);
    hint.textContent = bad ? (field.dataset.maskHint || 'Запись не как на бланке') : '';
    hint.hidden = !bad;
    wrap.classList.toggle('mask-format-bad', bad);
  }

  function bindMathMirrors(root) {
    root.querySelectorAll('math-field[data-mirror]').forEach(function (field) {
      if (field.dataset.mirrorBound) return;
      var name = field.dataset.mirror;
      var wrap = field.closest('.formula-field');
      var hidden = wrap && wrap.querySelector('input[name="' + name + '"]');
      if (!hidden) return;
      field.dataset.mirrorBound = '1';
      function sync(type) {
        hidden.value = mirrorValue(field);
        if (field.dataset.maskFormat) showFormatHint(field, wrap, hidden.value);
        if (type) hidden.dispatchEvent(new Event(type, {bubbles: true}));
      }
      field.addEventListener('input', function () { sync(); });
      field.addEventListener('change', function () { sync('change'); });
      sync();
    });
  }

  // Клавиатура принадлежит окну с активным полем, иначе native dialog
  // оставляет её под модальным слоем независимо от z-index.
  document.addEventListener('focusin', function(e) {
    if (!e.target.matches('math-field') || !window.mathVirtualKeyboard) return;
    var modal=e.target.closest('dialog[open]'), keyboard=window.mathVirtualKeyboard;
    if(modal){
      var host=modal.querySelector('[data-mask-keyboard]');
      if(!host){host=document.createElement('div');host.dataset.maskKeyboard='1';host.style.position='relative';modal.appendChild(host);}
      keyboard.container=host;
      if(!host.dataset.bound){host.dataset.bound='1';keyboard.addEventListener('geometrychange',function(){
        host.style.height=modal.open && keyboard.container===host ? keyboard.boundingRect.height+'px' : '0px';
      });}
    }else keyboard.container=document.body;
  });
  document.addEventListener('close', function(e) {
    if (e.target.tagName === 'DIALOG' && window.mathVirtualKeyboard) {
      window.mathVirtualKeyboard.hide();
      window.mathVirtualKeyboard.container = document.body;
    }
  }, true);

  function enhance(root) {
    bindMathMirrors(root);
    bindSetSlots(root);
    bindOrderSlots(root);
    root.querySelectorAll('[data-mask-order]').forEach(enhanceOrderSlot);
    if (window.EgorNumberLine) EgorNumberLine.init(root);
  }

  document.addEventListener('DOMContentLoaded', function () { enhance(document); });
  /* Для разметки, вставленной позже (превью маски в форме задачи) */
  window.EgorMask = {enhance: enhance, value: mirrorValue};
})();
