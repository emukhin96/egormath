/* Split-редактор PDF: слева tex-код, справа собранный PDF.
   «Собрать PDF» шлёт код на сервер и показывает результат в iframe;
   быстрые переключатели (размер/шрифт/бумага) правят код и пересобирают. */
(function () {
  'use strict';

  // Шрифт переключается штатной опцией пакета egor:
  // \usepackage[font=cm|school|palatino]{egor} (см. документацию egor.sty).
  var EGOR_RE = /\\usepackage(?:\[([^\]]*)\])?\{egor\}/;

  function setEgorFont(tex, value) {
    return tex.replace(EGOR_RE, function (_m, opts) {
      var parts = (opts || '').split(',')
        .map(function (s) { return s.trim(); })
        .filter(function (s) { return s && s.indexOf('font=') !== 0; });
      if (value !== 'cm') parts.push('font=' + value);
      return parts.length
        ? '\\usepackage[' + parts.join(',') + ']{egor}'
        : '\\usepackage{egor}';
    });
  }

  function getEgorFont(tex) {
    var opts = (tex.match(EGOR_RE) || [])[1] || '';
    var m = opts.match(/font=(cm|school|palatino)/);
    return m ? m[1] : 'cm';
  }

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
    var controller = null;

    // PDF и ссылка скачивания всегда соответствуют последней сборке:
    // при старте новой (или ошибке) старый результат убирается,
    // а незавершённый запрос отменяется — устаревший ответ не может
    // перезаписать актуальный.
    function clearResult() {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = null;
      frame.removeAttribute('src');
      download.hidden = true;
      download.removeAttribute('href');
    }

    function compile() {
      if (controller) controller.abort();
      controller = new AbortController();
      clearResult();
      status.textContent = 'Сборка…';
      log.hidden = true;
      var body = new URLSearchParams();
      body.append('tex', source.value);
      fetch(root.dataset.compileUrl, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf,
                  'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.toString(),
        signal: controller.signal,
      }).then(function (r) {
        if (r.ok) return r.blob().then(function (blob) {
          currentUrl = URL.createObjectURL(blob);
          // navpanes=0 прячет боковую панель миниатюр страниц во встроенном
          // просмотрщике (как в Adobe Acrobat по умолчанию)
          frame.src = currentUrl + '#navpanes=0&view=FitH';
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
      }).catch(function (err) {
        if (err && err.name === 'AbortError') return;
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
        tex = setEgorFont(tex, value);
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
        font: getEgorFont(tex),
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
