/* Страница задания ученика: подтверждение отправки с числом задач без ответа.
   Считается по текущему состоянию формы (поля и фото), а не по данным на
   момент загрузки — автосохранение могло уже изменить ответы. */
(function () {
  'use strict';

  function cardAnswered(card) {
    /* math-field не участвует в форме сам — его значение читаем напрямую */
    var controls = card.querySelectorAll('input:not([type=hidden]), textarea, math-field');
    for (var i = 0; i < controls.length; i++) {
      if ((controls[i].value || '').trim()) return true;
    }
    return !!card.querySelector('[data-photos] img');
  }

  /* Режим самопроверки: сервер возвращает результат сверки в ответе
     автосохранения, бейджи обновляются без перезагрузки. Разметка бейджа —
     как в _check_badge.html. */
  var BADGES = {
    ok: ['badge-reviewed', '✓ совпало', 'Совпало с эталоном'],
    wrong: ['badge-returned', '✗ не совпало', 'Не совпало с эталоном — проверьте запись'],
    unknown: ['badge-assigned', '? не разобрано', 'Автосверка не смогла разобрать ответ; учитель проверит вручную'],
  };

  function renderBadge(holder, status) {
    holder.dataset.status = status || '';
    holder.textContent = '';
    var spec = BADGES[status];
    if (!spec) return;
    var badge = document.createElement('span');
    badge.className = 'badge ' + spec[0];
    badge.textContent = spec[1];
    badge.title = spec[2];
    holder.appendChild(badge);
  }

  document.addEventListener('autosave:done', function (e) {
    var checks = e.detail && e.detail.checks;
    if (!checks) return;
    Object.keys(checks).forEach(function (prefix) {
      var holder = document.querySelector('[data-check="' + prefix + '"]');
      if (holder) renderBadge(holder, checks[prefix]);
    });
  });

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.getElementById('submit-assignment');
    if (!button) return;
    button.addEventListener('click', function (e) {
      var cards = document.querySelectorAll('[data-task-card]');
      var empty = [];
      cards.forEach(function (card) {
        if (!cardAnswered(card)) {
          var number = (card.id || '').replace('task-', '');
          if (number) empty.push(number);
        }
      });
      var text = 'Отправить работу на проверку? После этого изменить ответы будет нельзя.';
      if (empty.length === cards.length && cards.length) {
        text = 'Вы не ответили ни на одну задачу. Всё равно отправить на проверку?';
      } else if (empty.length) {
        text = 'Без ответа: № ' + empty.join(', ') + '. ' + text;
      }
      if (!window.confirm(text)) e.preventDefault();
    });
  });
})();
