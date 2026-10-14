/* Тумблер «ответы и решения»: #toggle-answers переключает .show-answers
   на #ws-items и атрибут hidden у блоков .ws-answers; #toggle-author-only
   (если есть) — класс .author-only, скрывающий AI-варианты.
   Ключ localStorage — data-answers-key (у подборки свой, чтобы не
   подхватывать состояние конструктора). */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('toggle-answers');
    var list = document.getElementById('ws-items');
    if (!toggle || !list) return;
    var KEY = list.getAttribute('data-answers-key') || 'ws-show-answers';
    function apply() {
      var on = toggle.checked;
      list.classList.toggle('show-answers', on);
      list.querySelectorAll('.ws-answers').forEach(function (el) {
        el.hidden = !on;
        if (on) el.querySelectorAll('.math-content').forEach(renderMathContent);
      });
      try { localStorage.setItem(KEY, on ? '1' : ''); } catch (e) {}
    }
    try { toggle.checked = localStorage.getItem(KEY) === '1'; } catch (e) {}
    apply();
    toggle.addEventListener('change', apply);
    document.addEventListener('worksheet:updated', apply);

    // «Только из задачника»: #toggle-author-only прячет AI-ответы и решения
    // (.author-only на #ws-items, правила в input.css). Ключ — data-storage-key.
    var authorOnly = document.getElementById('toggle-author-only');
    if (!authorOnly) return;
    var AUTHOR_KEY = authorOnly.getAttribute('data-storage-key') || 'ws-author-only';
    function applyAuthorOnly() {
      list.classList.toggle('author-only', authorOnly.checked);
      try { localStorage.setItem(AUTHOR_KEY, authorOnly.checked ? '1' : ''); } catch (e) {}
    }
    try { authorOnly.checked = localStorage.getItem(AUTHOR_KEY) === '1'; } catch (e) {}
    applyAuthorOnly();
    authorOnly.addEventListener('change', applyAuthorOnly);
    // Список подменили скриптом (предпросмотр листка и т.п.) — состояние
    // тумблера применяется заново, как и у «ответов и решений».
    document.addEventListener('worksheet:updated', applyAuthorOnly);
  });
})();
