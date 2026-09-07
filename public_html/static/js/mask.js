/* Поведение контролов маски ответа на странице ученика (разметка —
   _mask.html, серверная). Значения слотов уходят обычным автосохранением
   формы (autosave.js, событие change), math-field зеркалится в скрытый
   input в formula.js.

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

  function enhance(root) {
    bindSetSlots(root);
    bindOrderSlots(root);
    root.querySelectorAll('[data-mask-order]').forEach(enhanceOrderSlot);
    if (window.EgorNumberLine) EgorNumberLine.init(root);
  }

  document.addEventListener('DOMContentLoaded', function () { enhance(document); });
  /* Для разметки, вставленной позже (превью маски в форме задачи) */
  window.EgorMask = {enhance: enhance};
})();
