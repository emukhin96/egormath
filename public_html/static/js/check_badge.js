/* Бейдж автосверки — разметка как в _check_badge.html. Общий для страницы
   задания (assignment.js) и превью маски в форме задачи (mask_editor.js). */
(function () {
  'use strict';

  var BADGES = {
    ok: ['badge-reviewed', '✓ верно', 'Ответ совпал с эталоном'],
    wrong: ['badge-returned', '✗ неверно', 'Ответ не совпал с эталоном — проверьте запись'],
    format: ['badge-returned', '✗ не тот формат', 'Запись не в формате бланка — см. подсказку под полем'],
    unknown: ['badge-assigned', '? не разобрано', 'Автосверка не смогла разобрать ответ; учитель проверит вручную'],
  };

  function render(holder, status) {
    holder.dataset.status = status || '';
    holder.textContent = '';
    var spec = BADGES[status];
    if (!spec) return;
    var badge = document.createElement('span');
    badge.className = 'badge ' + spec[0];
    badge.textContent = spec[1];
    /* Подсказка о формате своя у каждого строгого поля (data-hint из _check_badge.html):
       для отношения — «через двоеточие», для десятичной дроби — «через запятую» */
    badge.title = (status === 'format' && holder.dataset.hint) ? holder.dataset.hint : spec[2];
    holder.appendChild(badge);
  }

  /* checks: {имя поля → статус}; ищет [data-check="имя"] внутри root */
  function apply(root, checks) {
    Object.keys(checks || {}).forEach(function (name) {
      var holder = (root || document).querySelector('[data-check="' + name + '"]');
      if (holder) render(holder, checks[name]);
    });
  }

  window.EgorCheckBadge = {render: render, apply: apply, BADGES: BADGES};
})();
