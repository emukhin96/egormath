/* Открытие/закрытие нативных <dialog>: кнопка с data-dialog-open="id"
   показывает диалог, любой элемент с data-dialog-close внутри — закрывает. */
(function () {
  'use strict';

  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-dialog-open]');
    if (opener) {
      var dialog = document.getElementById(opener.dataset.dialogOpen);
      if (dialog && typeof dialog.showModal === 'function') dialog.showModal();
      return;
    }
    if (e.target.closest('[data-dialog-close]')) {
      var open = e.target.closest('dialog');
      if (open) open.close();
    }
  });
})();
