/* Ввод формул на странице задания (MathLive, подключён с CDN).

   1. Поля <math-field> масок ответа зеркалит mask.js, чтобы и обычные
      формулы, и строгие форматы участвовали в автосохранении.
   2. Кнопка [data-formula-insert] рядом с textarea показывает панель
      #formula-panel прямо под этим полем (не <dialog>: экранная клавиатура
      MathLive рисуется в body и под модальным окном была недоступна) и
      вставляет набранное как $…$ в позицию курсора.
   3. Под textarea — превью [data-answer-preview]: текст с формулами
      рендерится KaTeX, чтобы ученик видел формулу, а не LaTeX-код. */
(function () {
  'use strict';

  function fire(el, type) {
    el.dispatchEvent(new Event(type, {bubbles: true}));
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

  /* --- Превью текста с формулами --- */

  function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderPreview(textarea) {
    var wrap = textarea.closest('.text-answer');
    var preview = wrap && wrap.querySelector('[data-answer-preview]');
    if (!preview) return;
    var text = textarea.value;
    var hasMath = /\$|\\\(|\\\[/.test(text);
    if (!hasMath || typeof renderMathInElement !== 'function') {
      preview.hidden = true;
      preview.textContent = '';
      return;
    }
    var html = escapeHtml(text).replace(/\n/g, '<br>');
    if (typeof protectDecimalCommas === 'function') html = protectDecimalCommas(html);
    preview.innerHTML = html;
    renderMathInElement(preview, {
      delimiters: [
        {left: '$$', right: '$$', display: true},
        {left: '\\[', right: '\\]', display: true},
        {left: '$', right: '$', display: false},
        {left: '\\(', right: '\\)', display: false},
      ],
      macros: {'\\degr': '^{\\circ}'},
      throwOnError: false,
    });
    preview.hidden = false;
  }

  function bindPreviews() {
    document.querySelectorAll('.text-answer textarea').forEach(function (textarea) {
      var timer = null;
      textarea.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { renderPreview(textarea); }, 150);
      });
      renderPreview(textarea);
    });
  }

  /* --- Панель вставки формулы --- */

  function bindPanel() {
    var panel = document.getElementById('formula-panel');
    var field = document.getElementById('formula-panel-field');
    if (!panel || !field) return;
    var target = null;

    function close() {
      panel.hidden = true;
      if (target) target.focus();
      target = null;
    }

    function confirm() {
      var latex = (field.value || '').trim();
      var textarea = target;
      if (latex && textarea) insertAtCursor(textarea, '$' + latex + '$');
      close();
    }

    document.addEventListener('click', function (e) {
      var opener = e.target.closest('[data-formula-insert]');
      if (!opener) return;
      var wrap = opener.closest('.text-answer');
      var textarea = wrap && wrap.querySelector('textarea');
      if (!textarea) return;
      if (target === textarea && !panel.hidden) { close(); return; }
      target = textarea;
      field.value = '';
      var row = wrap.querySelector('.text-answer-row');
      row.insertAdjacentElement('afterend', panel);
      panel.hidden = false;
      setTimeout(function () { field.focus(); }, 50);
    });

    panel.querySelector('[data-formula-confirm]').addEventListener('click', confirm);
    panel.querySelector('[data-formula-cancel]').addEventListener('click', close);
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        confirm();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindPreviews();
    bindPanel();
  });
})();
