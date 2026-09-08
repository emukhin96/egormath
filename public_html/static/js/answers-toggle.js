/* Тумблер «ответы и решения»: #toggle-answers переключает .show-answers
   на #ws-items и атрибут hidden у блоков .ws-answers.
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
      });
      try { localStorage.setItem(KEY, on ? '1' : ''); } catch (e) {}
    }
    try { toggle.checked = localStorage.getItem(KEY) === '1'; } catch (e) {}
    apply();
    toggle.addEventListener('change', apply);
  });
})();
