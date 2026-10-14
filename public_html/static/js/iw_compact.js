/* Компактный вид состава самостоятельной (#iw-compact, шаблон
   independentworks/_compact.html): переключатель «Подробно | Компактно»,
   перетаскивание номеров и плашек кандидатов, выбор номеров для
   объединения, подсказки «Похожи» и тост с «Отменить».
   Сервер после переноса или объединения отвечает JSON; страница
   перезагружается и показывает тост из #iw-undo. */
(function () {
  'use strict';

  var VIEW_KEY = 'iw-view';
  var HIDE_KEY = 'iw-similar-hide:';
  var HINT_LIMIT = 3;

  function stored(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) {}
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.getElementById('iw-compact');
    if (!root) return;
    var card = root.closest('.worksheet-items-card');
    var showSaved = window.EgorAutosave ? window.EgorAutosave.showSaved : function () {};
    var csrf = root.querySelector('input[name=csrfmiddlewaretoken]');

    function post(url, data) {
      var body = new URLSearchParams();
      Object.keys(data).forEach(function (key) { body.append(key, data[key]); });
      return fetch(url, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf ? csrf.value : '',
                  'X-Requested-With': 'XMLHttpRequest',
                  'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.toString(),
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (json) {
          if (!r.ok) throw new Error(json.message || 'Не удалось сохранить изменение');
          return json;
        });
      }, function () { throw new Error('Нет связи — изменение не сохранено'); });
    }

    // --- Переключатель вида ---
    function applyView(mode) {
      var compact = mode === 'compact';
      root.hidden = !compact;
      if (card) card.classList.toggle('is-compact', compact);
      document.querySelectorAll('input[name="iw-view"]').forEach(function (radio) {
        radio.checked = radio.value === (compact ? 'compact' : 'detailed');
      });
    }
    applyView(stored(VIEW_KEY) === 'compact' ? 'compact' : 'detailed');
    document.querySelectorAll('input[name="iw-view"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        if (!radio.checked) return;
        store(VIEW_KEY, radio.value === 'compact' ? 'compact' : '');
        applyView(radio.value);
      });
    });

    // Ответы в плашках подчиняются общему тумблеру «ответы и решения».
    var answers = document.getElementById('toggle-answers');
    function applyAnswers() { root.classList.toggle('show-answers', !!(answers && answers.checked)); }
    if (answers) answers.addEventListener('change', applyAnswers);
    applyAnswers();

    // --- Тост после переноса или объединения ---
    var undo = document.getElementById('iw-undo');
    if (undo) {
      showSaved(true, undo.dataset.message, {label: 'Отменить', onClick: function () {
        post(root.dataset.undoUrl, {token: undo.dataset.token})
          .then(function () { location.reload(); })
          .catch(function (error) { showSaved(false, error.message); });
      }});
    }

    function merge(ids) {
      post(root.dataset.mergeUrl, {ids: ids.join(',')})
        .then(function () { location.reload(); })
        .catch(function (error) { showSaved(false, error.message); });
    }

    // --- Выбор номеров и объединение без мыши ---
    var selbar = root.querySelector('[data-selbar]');
    var checks = Array.prototype.slice.call(root.querySelectorAll('.iw-compact-check'));
    function chosen() { return checks.filter(function (box) { return box.checked; }); }
    function listNumbers(boxes) {
      var labels = boxes.map(function (box) { return '№' + box.dataset.number; });
      if (labels.length < 2) return labels.join('');
      return labels.slice(0, -1).join(', ') + ' и ' + labels[labels.length - 1];
    }
    function updateSelbar() {
      var boxes = chosen();
      selbar.hidden = boxes.length < 2;
      selbar.querySelector('[data-selbar-text]').textContent = 'Выбрано: ' + listNumbers(boxes);
      checks.forEach(function (box) {
        box.closest('.iw-compact-pos').classList.toggle('is-selected', box.checked);
      });
    }
    checks.forEach(function (box) { box.addEventListener('change', updateSelbar); });
    if (selbar) {
      updateSelbar();
      selbar.querySelector('[data-merge-selected]').addEventListener('click', function () {
        merge(chosen().map(function (box) { return box.value; }));
      });
      selbar.querySelector('[data-clear-selection]').addEventListener('click', function () {
        checks.forEach(function (box) { box.checked = false; });
        updateSelbar();
      });
    }

    // --- Подсказки «Похожи»: не больше трёх нескрытых ---
    var shown = 0;
    root.querySelectorAll('.iw-compact-hint').forEach(function (hint) {
      var key = HIDE_KEY + hint.dataset.hint;
      if (stored(key) === '1' || shown >= HINT_LIMIT) return;
      shown += 1;
      hint.hidden = false;
      hint.querySelector('[data-hide-hint]').addEventListener('click', function () {
        store(key, '1');
        hint.hidden = true;
      });
      hint.querySelector('[data-merge]').addEventListener('click', function () {
        merge(hint.querySelector('[data-merge]').dataset.merge.split(','));
      });
    });

    if (typeof Sortable === 'undefined') return;
    var list = root.querySelector('[data-compact-list]');

    // --- Порядок номеров: тот же контракт, что у подробного вида ---
    Sortable.create(list, {
      handle: '.iw-compact-handle',
      draggable: '.iw-compact-pos',
      animation: 150,
      ghostClass: 'ws-ghost',
      onEnd: function (evt) {
        if (evt.oldIndex === evt.newIndex) return;
        var ids = Array.prototype.map.call(list.querySelectorAll('.iw-compact-pos'),
          function (el) { return el.dataset.position; });
        post(root.dataset.reorderUrl, {order: ids.join(',')})
          .then(function () { location.reload(); })
          .catch(function (error) { showSaved(false, error.message); setTimeout(function () { location.reload(); }, 1500); });
      },
    });

    // --- Плашки: на другой номер или в промежуток между номерами ---
    var dropTarget = null;
    function highlight(target) {
      if (dropTarget === target) return;
      if (dropTarget) dropTarget.classList.remove('is-drop');
      dropTarget = target;
      if (dropTarget) dropTarget.classList.add('is-drop');
    }
    function targetOf(container, from) {
      if (!container || container === from) return null;
      return container.classList.contains('iw-compact-gap') ? container : container.closest('.iw-compact-pos');
    }

    var options = {
      handle: '.iw-compact-grip',
      draggable: '.iw-compact-cand',
      sort: false,
      animation: 120,
      ghostClass: 'iw-compact-ghost',
      onStart: function () { root.classList.add('is-dragging'); },
      onMove: function (evt) {
        highlight(targetOf(evt.to, evt.from));
      },
      onEnd: function (evt) {
        root.classList.remove('is-dragging');
        highlight(null);
        if (evt.to === evt.from) return;
        var data = {candidate: evt.item.dataset.candidate};
        if (evt.to.classList.contains('iw-compact-gap')) data.before = evt.to.dataset.before;
        else data.target = evt.to.dataset.target;
        post(root.dataset.moveUrl, data).then(function () {
          location.reload();
        }).catch(function (error) {
          // Вернуть плашку на место: сервер ничего не изменил.
          evt.from.insertBefore(evt.item, evt.from.children[evt.oldIndex] || null);
          showSaved(false, error.message);
        });
      },
    };
    root.querySelectorAll('.iw-compact-cands').forEach(function (cands) {
      Sortable.create(cands, Object.assign({}, options, {
        group: {name: 'iw-cand', pull: true, put: cands.dataset.closed !== '1'},
      }));
    });
    root.querySelectorAll('.iw-compact-gap').forEach(function (gap) {
      Sortable.create(gap, Object.assign({}, options, {
        group: {name: 'iw-cand', pull: false, put: true},
        draggable: '.iw-compact-cand',
      }));
    });
  });
})();
