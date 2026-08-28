(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll('.import-status-button'));
    var feedback = document.querySelector('.import-status-feedback');
    if (!buttons.length) return;
    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        var radio = document.getElementById(button.dataset.radioId);
        if (!radio) return;
        radio.checked = true;
        buttons.forEach(function (other) {
          var active = other === button;
          other.classList.toggle('is-active', active);
          other.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (feedback) feedback.textContent = 'Выбрано: ' + button.textContent.trim();
      });
    });
  });
})();
