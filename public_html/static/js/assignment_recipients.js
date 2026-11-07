/* Диалог «Изменить получателей» в списке заданий.

   Диалоги на каждую работу не рендерятся: в странице один
   <template id="assignment-recipient-dialog"> и JSON #recipient-dialogs
   (см. assignments.views.recipient_dialogs_data). При нажатии кнопки
   data-dialog-open="assignment-group-<key>" диалог собирается здесь — в фазе
   перехвата, чтобы dialogs.js затем нашёл его по id и открыл как обычно.
   Собранный диалог остаётся в документе: повторное открытие показывает
   его в том же состоянии, как раньше статическая разметка.

   Поля формы — как у серверной разметки: чекбокс students, select
   status_<id> (обычные) или variant_<id> (самостоятельные); закреплённый
   ученик — отключённые контролы плюс hidden-поля с теми же именами. */
(function () {
  'use strict';

  var PREFIX = 'assignment-group-';
  var dataNode = document.getElementById('recipient-dialogs');
  var template = document.getElementById('assignment-recipient-dialog');
  if (!dataNode || !template || !('content' in template)) return;
  var data = JSON.parse(dataNode.textContent);

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) { node.setAttribute(name, attrs[name]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function studentName(id) {
    return data.students[String(id)] || String(id);
  }

  function labelFor(id, box, suffix) {
    var label = el('label');
    label.appendChild(box);
    label.appendChild(document.createTextNode(' '));
    label.appendChild(el('span', {}, studentName(id) + (suffix || '')));
    return label;
  }

  /* [id, статус | null, можно ли отметить «Проверено»] */
  function ordinaryRow(item) {
    var id = item[0], status = item[1], canReview = item[2];
    var row = el('div', {'class': 'assignment-recipient-row'});
    var box = el('input', {type: 'checkbox', name: 'students', value: id});
    if (status !== null) { box.checked = true; box.setAttribute('data-existing', ''); }
    row.appendChild(labelFor(id, box));
    var select = el('select', {name: 'status_' + id, 'aria-label': 'Статус: ' + studentName(id)});
    data.statuses.forEach(function (pair) {
      var option = el('option', {value: pair[0]}, pair[1]);
      if (status === pair[0] || (status === null && pair[0] === 'assigned')) option.selected = true;
      if (pair[0] === 'reviewed' && !canReview) option.disabled = true;
      select.appendChild(option);
    });
    row.appendChild(select);
    return row;
  }

  /* [id, вариант | null, закреплён ли, подпись состояния] */
  function independentRow(item, variants) {
    var id = item[0], variantId = item[1], locked = item[2], state = item[3];
    var row = el('div', {'class': 'assignment-recipient-row'});
    var box = el('input', {type: 'checkbox', name: 'students', value: id});
    if (variantId !== null) box.checked = true;
    if (locked) box.disabled = true;
    row.appendChild(labelFor(id, box, locked ? ', ' + state : ''));
    if (locked) row.appendChild(el('input', {type: 'hidden', name: 'students', value: id}));
    var select = el('select', {name: 'variant_' + id, 'aria-label': 'Вариант: ' + studentName(id)});
    if (locked) select.disabled = true;
    variants.forEach(function (variant) {
      var option = el('option', {value: variant[0]}, 'Вариант ' + variant[1]);
      if (variantId === variant[0]) option.selected = true;
      select.appendChild(option);
    });
    row.appendChild(select);
    if (locked) row.appendChild(el('input', {type: 'hidden', name: 'variant_' + id, value: variantId}));
    return row;
  }

  function build(key) {
    var group = data.groups[key];
    if (!group) return null;
    var fragment = template.content.cloneNode(true);
    var dialog = fragment.querySelector('dialog');
    var form = dialog.querySelector('form');
    dialog.id = PREFIX + key;
    form.setAttribute('action', group.action);
    /* Подтверждение снятия учеников (data-assignment-group-form) — только у обычных заданий */
    if (group.kind !== 'ordinary' && group.kind !== 'collection') form.removeAttribute('data-assignment-group-form');
    dialog.querySelector('h3').textContent = group.title;
    Array.prototype.forEach.call(dialog.querySelectorAll('[data-hint]'), function (hint) {
      if (hint.dataset.hint !== group.kind) hint.remove();
    });
    var list = dialog.querySelector('.assignment-recipient-list');
    if (group.rows.length) {
      list.querySelector('[data-empty]').remove();
      group.rows.forEach(function (item) {
        list.appendChild(group.kind === 'independent' ? independentRow(item, group.variants) : ordinaryRow(item));
      });
    }
    document.body.appendChild(fragment);
    return dialog;
  }

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-dialog-open]');
    if (!opener) return;
    var id = opener.dataset.dialogOpen;
    if (id.indexOf(PREFIX) !== 0 || document.getElementById(id)) return;
    build(id.slice(PREFIX.length));
  }, true);
})();
