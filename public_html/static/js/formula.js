/* Ввод формул на странице задания (MathLive, подключён с CDN).

   1. <math-field data-mirror="имя"> — поле ответа типа «формула». Элемент не
      участвует в форме, поэтому его LaTeX зеркалится в скрытый <input>;
      событие change на нём запускает автосохранение формы (autosave.js).
   2. Кнопка [data-formula-insert] рядом с textarea открывает <dialog
      id="formula-dialog"> и вставляет набранное как $…$ в позицию курсора —
      текстовые ответы («нет решений») остаются обычным текстом. */
(function () {
  'use strict';

  function fire(el, type) {
    el.dispatchEvent(new Event(type, {bubbles: true}));
  }

  function bindMirrors() {
    document.querySelectorAll('math-field[data-mirror]').forEach(function (mf) {
      var form = mf.closest('form');
      var hidden = form && form.querySelector('input[name="' + mf.dataset.mirror + '"]');
      if (!hidden || mf.dataset.mirrorBound) return;
      mf.dataset.mirrorBound = '1';
      mf.addEventListener('input', function () { hidden.value = mf.value; });
      mf.addEventListener('change', function () {
        hidden.value = mf.value;
        fire(hidden, 'change');
      });
    });
  }

  function insertAtCursor(textarea, snippet) {
    var start = textarea.selectionStart, end = textarea.selectionEnd;
    var before = textarea.value.slice(0, start), after = textarea.value.slice(end);
    var pad = before && !/\s$/.test(before) ? ' ' : '';
    textarea.value = before + pad + snippet + after;
    var pos = (before + pad + snippet).length;
    textarea.focus();
    textarea.setSelectionRange(pos, pos);
    fire(textarea, 'input');
    fire(textarea, 'change');
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindMirrors();

    var dialog = document.getElementById('formula-dialog');
    var field = document.getElementById('formula-dialog-field');
    if (!dialog || !field || typeof dialog.showModal !== 'function') return;
    var target = null;

    document.addEventListener('click', function (e) {
      var opener = e.target.closest('[data-formula-insert]');
      if (!opener) return;
      var wrap = opener.closest('.text-answer');
      target = wrap && wrap.querySelector('textarea');
      if (!target) return;
      field.value = '';
      dialog.showModal();
      setTimeout(function () { field.focus(); }, 50);
    });

    function confirm() {
      var latex = (field.value || '').trim();
      if (latex && target) insertAtCursor(target, '$' + latex + '$');
      dialog.close();
    }

    dialog.querySelector('[data-formula-confirm]').addEventListener('click', confirm);
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        confirm();
      }
    });
  });
})();
