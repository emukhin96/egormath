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
