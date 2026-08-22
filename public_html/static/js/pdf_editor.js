/* Split-редактор PDF: слева tex-код, справа собранный PDF.
   «Собрать PDF» шлёт код на сервер и показывает результат в iframe;
   быстрые переключатели (размер/шрифт/бумага) правят код и пересобирают. */
(function () {
  'use strict';

  // Строки, которые добавляет переключатель шрифта (вставляются после egor).
  // Сервер собирает LuaLaTeX, поэтому шрифты меняем через fontspec.
  var FONT_LINES = {
    cm: [],
    schoolbook: ['\\usepackage{fontspec}',
                 '\\setmainfont{TeX Gyre Schola}'],
    palatino: ['\\usepackage{fontspec}',
               '\\setmainfont{TeX Gyre Pagella}'],
  };
  var ALL_FONT_LINES = [
    '\\usepackage{fontspec}',
    '\\setmainfont{TeX Gyre Schola}',
    '\\setmainfont{TeX Gyre Pagella}',
  ];

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('.pdf-editor');
    if (!root) return;
    var source = document.getElementById('tex-source');
    var original = document.getElementById('tex-original');
    var frame = document.getElementById('pdf-frame');
    var log = document.getElementById('compile-log');
    var status = document.getElementById('compile-status');
    var download = document.getElementById('download-btn');
    var csrf = root.querySelector('input[name=csrfmiddlewaretoken]').value;
    var currentUrl = null;

    function compile() {
      status.textContent = 'Сборка…';
      log.hidden = true;
      var body = new URLSearchParams();
      body.append('tex', source.value);
      fetch(root.dataset.compileUrl, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf,
                  'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.toString(),
      }).then(function (r) {
        if (r.ok) return r.blob().then(function (blob) {
          if (currentUrl) URL.revokeObjectURL(currentUrl);
          currentUrl = URL.createObjectURL(blob);
          frame.src = currentUrl;
          download.href = currentUrl;
          download.hidden = false;
          status.textContent = '';
        });
        return r.json().then(function (data) {
          status.textContent = data.message || 'Ошибка компиляции';
          if (data.log) {
            log.textContent = data.log;
            log.hidden = false;
          }
        });
      }).catch(function () {
        status.textContent = 'Нет связи с сервером';
      });
    }

    // --- Быстрые переключатели: типовые правки кода ---
    function applySwitch(kind, value) {
      var tex = source.value;
      if (kind === 'size') {
        tex = tex.replace(/\b1[012]pt\b/, value);
      } else if (kind === 'paper') {
        tex = tex.replace(/\ba[45]paper\b/, value);
      } else if (kind === 'font') {
        var lines = tex.split('\n').filter(function (line) {
          return ALL_FONT_LINES.indexOf(line.trim()) === -1;
        });
        var extra = FONT_LINES[value] || [];
        if (extra.length) {
          for (var i = 0; i < lines.length; i += 1) {
            if (/\\usepackage(\[[^\]]*\])?\{egor\}/.test(lines[i])) {
              lines.splice.apply(lines, [i + 1, 0].concat(extra));
              break;
            }
          }
        }
        tex = lines.join('\n');
      }
      source.value = tex;
      markActive();
      compile();
    }

    function markActive() {
      var tex = source.value;
      var current = {
        size: (tex.match(/\b(1[012]pt)\b/) || [])[1] || '',
        paper: (tex.match(/\b(a[45]paper)\b/) || [])[1] || '',
        font: tex.indexOf('TeX Gyre Schola') !== -1 ? 'schoolbook'
          : tex.indexOf('TeX Gyre Pagella') !== -1 ? 'palatino' : 'cm',
      };
      document.querySelectorAll('.switch-group').forEach(function (group) {
        group.querySelectorAll('button').forEach(function (btn) {
          btn.classList.toggle(
            'is-active', btn.dataset.value === current[group.dataset.switch]);
        });
      });
    }

    document.querySelectorAll('.switch-group button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        applySwitch(btn.closest('.switch-group').dataset.switch,
                    btn.dataset.value);
      });
    });

    document.getElementById('compile-btn').addEventListener('click', compile);
    document.getElementById('reset-btn').addEventListener('click', function () {
      source.value = original.value;
      markActive();
      compile();
    });

    markActive();
    compile();
  });
})();
