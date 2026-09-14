(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('toggle-import-draft-answers');
    var list = document.getElementById('import-drafts');
    if (!toggle || !list) return;
    var KEY = 'import-show-answers';
    function apply() {
      list.classList.toggle('show-answers', toggle.checked);
      list.querySelectorAll('.ws-answers').forEach(function (el) {
        el.hidden = !toggle.checked;
        if (toggle.checked) el.querySelectorAll('.math-content').forEach(renderMathContent);
      });
      try { localStorage.setItem(KEY, toggle.checked ? '1' : ''); } catch (e) {}
    }
    try { toggle.checked = localStorage.getItem(KEY) === '1'; } catch (e) {}
    apply();
    toggle.addEventListener('change', apply);
  });
})();
