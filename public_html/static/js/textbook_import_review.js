(function () {
  'use strict';

  function wrapMathField(textarea) {
    var start = textarea.selectionStart;
    var end = textarea.selectionEnd;
    var value = textarea.value;
    if (start === end) {
      start = 0;
      end = value.length;
    }
    var selected = value.slice(start, end);
    var lead = (selected.match(/^\s*/) || [''])[0];
    var trail = (selected.match(/\s*$/) || [''])[0];
    var core = selected.slice(lead.length, selected.length - trail.length);
    if (!core) return;
    if (/^\$[\s\S]*\$$/.test(core) || /^\\\([\s\S]*\\\)$/.test(core)) return;
    var wrapped = lead + '$' + core + '$' + trail;
    textarea.value = value.slice(0, start) + wrapped + value.slice(end);
    textarea.focus();
    textarea.selectionStart = start + lead.length;
    textarea.selectionEnd = start + wrapped.length - trail.length;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll('.import-status-button'));
    var feedback = document.querySelector('.import-status-feedback');
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

    Array.prototype.slice.call(
      document.querySelectorAll('.import-wrap-math')).forEach(function (button) {
      button.addEventListener('click', function () {
        var field = document.getElementById(button.getAttribute('data-wrap-math'));
        if (field) wrapMathField(field);
      });
    });
  });
})();
