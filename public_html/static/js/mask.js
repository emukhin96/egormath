/* Поведение контролов маски ответа на странице ученика (разметка —
   _mask.html, серверная). Значения слотов уходят обычным автосохранением
   формы (autosave.js, событие change), math-field зеркалится в скрытый
   input в formula.js.

   1. Слот «множество»: флажок «решений нет» очищает и блокирует поле чисел
      (сервер при флажке пишет ∅, что бы ни было в поле).
   2. Слот «порядок»: выбор элемента на одном месте снимает его с других мест,
      чтобы один элемент не стоял дважды. */
(function () {
  'use strict';

  function bindSetSlots(root) {
    root.querySelectorAll('[data-mask-none]').forEach(function (box) {
      var wrap = box.closest('.mask-set');
      var input = wrap && wrap.querySelector('.mask-set-input');
      if (!input) return;
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

  document.addEventListener('DOMContentLoaded', function () {
    bindSetSlots(document);
    bindOrderSlots(document);
  });
})();
