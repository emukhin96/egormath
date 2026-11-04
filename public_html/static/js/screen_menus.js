/* Экраны «Задания и ученики» (ревизия 03.11): выпадающая кнопка
   «Добавить ученика ▾», окна из пунктов меню «⋯», переименование группы
   на месте и подтверждение удаления. Меню «⋯» закрывает shell.js; здесь —
   только то, что он не делает. */
(function () {
  'use strict';

  function closeAddMenus(except) {
    document.querySelectorAll('details[data-add-menu][open]').forEach(function (menu) {
      if (menu !== except) menu.open = false;
    });
  }

  document.addEventListener('click', function (event) {
    closeAddMenus(event.target.closest('details[data-add-menu]'));
    // Пункт меню открывает окно — меню за окном больше не нужно
    var opener = event.target.closest('.more-menu-list [data-dialog-open]');
    if (opener) opener.closest('details').open = false;

    var rename = event.target.closest('[data-group-rename]');
    if (rename) {
      var row = rename.closest('[data-group-row]');
      var form = row.querySelector('[data-group-rename-form]');
      row.classList.add('is-renaming');
      form.hidden = false;
      var input = form.querySelector('input[name=name]');
      input.focus();
      input.select();
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    closeAddMenus();
    var form = event.target.closest && event.target.closest('[data-group-rename-form]');
    if (form) {
      var input = form.querySelector('input[name=name]');
      input.value = input.defaultValue;
      form.hidden = true;
      form.closest('[data-group-row]').classList.remove('is-renaming');
    }
  });

  document.addEventListener('submit', function (event) {
    var text = event.target.dataset && event.target.dataset.confirm;
    if (text && !confirm(text)) event.preventDefault();
  });

  // Окно с ошибками формы после отправки открывается снова
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('dialog[data-open-on-load]').forEach(function (dialog) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
    });
  });
})();
