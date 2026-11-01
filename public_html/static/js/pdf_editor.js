/* Split-редактор PDF: слева tex-код, справа собранный PDF.
   «Собрать PDF» шлёт код на сервер и показывает результат в iframe;
   быстрые переключатели (вариант/размер/шрифт/бумага/режим) только правят
   код и никогда не запускают сборку — их можно выбирать в любом порядке. */
(function () {
  'use strict';

  // Шрифт и режим переключаются штатными опциями пакета egor:
  // \usepackage[font=cm|school|palatino|stix,diagn]{egor} (см. egor.sty).
  var EGOR_RE = /\\usepackage(?:\[([^\]]*)\])?\{egor\}/;

  function egorOptions(tex) {
    return ((tex.match(EGOR_RE) || [])[1] || '').split(',')
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function withEgorOptions(tex, parts) {
    return tex.replace(EGOR_RE, function () {
      return parts.length
        ? '\\usepackage[' + parts.join(',') + ']{egor}'
        : '\\usepackage{egor}';
    });
  }

  function setEgorFont(tex, value) {
    var parts = egorOptions(tex).filter(function (s) {
      return s.indexOf('font=') !== 0;
    });
    if (value !== 'cm') parts.push('font=' + value);
    return withEgorOptions(tex, parts);
  }

  function getEgorFont(tex) {
    var m = egorOptions(tex).join(',').match(/font=(cm|school|palatino|stix)/);
    return m ? m[1] : 'cm';
  }

  // diagn — режим диагностической работы (номера задач в рамках)
  function setEgorDiagn(tex, on) {
    var parts = egorOptions(tex).filter(function (s) { return s !== 'diagn'; });
    if (on === 'on') parts.push('diagn');
    return withEgorOptions(tex, parts);
  }

  function getEgorDiagn(tex) {
    return egorOptions(tex).indexOf('diagn') !== -1 ? 'on' : 'off';
  }

  // Оформление, которое переносится при смене варианта
  function readOptions(tex) {
    return {
      size: (tex.match(/\b(1[012]pt)\b/) || [])[1] || '',
      paper: (tex.match(/\b(a[45]paper)\b/) || [])[1] || '',
      font: getEgorFont(tex),
      diagn: getEgorDiagn(tex),
    };
  }

  function applyOption(tex, kind, value) {
    if (!value) return tex;
    if (kind === 'size') return tex.replace(/\b1[012]pt\b/, value);
    if (kind === 'paper') return tex.replace(/\ba[45]paper\b/, value);
    if (kind === 'font') return setEgorFont(tex, value);
    if (kind === 'diagn') return setEgorDiagn(tex, value);
    return tex;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('.pdf-editor');
    if (!root) return;
    var source = document.getElementById('tex-source');
    var original = document.getElementById('tex-original');
    var log = document.getElementById('compile-log');
    var status = document.getElementById('compile-status');
    var download = document.getElementById('download-btn');
    var csrf = root.querySelector('input[name=csrfmiddlewaretoken]').value;
    var variants = {};
    JSON.parse(document.getElementById('pdf-variants').textContent)
      .forEach(function (v) { variants[v.value] = v; });
    var compileButtons = Array.prototype.slice.call(
      document.querySelectorAll('[data-pdf-compile]'));
    var preview = window.EgorPdfPreview(
      root.querySelector('.pdf-preview'), compileButtons);
    var variant = root.dataset.variant;
    var editedByHand = false;
    var currentUrl = null;
    var inFlight = false;
    var inFlightKey = null;
    var builtKey = null;
    var pending = false;

    // Что именно собирается: вариант и код целиком
    function buildKey() {
      return variant + '\n' + source.value;
    }

    // PDF и ссылка скачивания всегда соответствуют последней сборке:
    // при старте новой (или ошибке) старый результат убирается.
    function clearResult() {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = null;
      builtKey = null;
      download.hidden = true;
      download.removeAttribute('href');
    }

    // После любой правки параметров или кода PDF на экране — «устаревший»
    function refreshStale() {
      preview.stale(builtKey !== null && builtKey !== buildKey());
    }

    // Сборки сериализуются, а не отменяются: abort закрыл бы только fetch
    // в браузере, серверная компиляция продолжила бы держать lock, и новый
    // запрос получил бы 429. Повторный клик во время сборки с изменённым
    // кодом лишь помечает pending; по завершении устаревший результат
    // отбрасывается и сборка запускается заново с актуальным кодом.
    function compile() {
      if (inFlight) {
        if (inFlightKey !== buildKey()) pending = true;
        return;
      }
      inFlight = true;
      inFlightKey = buildKey();
      clearResult();
      preview.busy();
      status.textContent = '';
      log.hidden = true;
      var body = new URLSearchParams();
      body.append('tex', source.value);
      body.append('variant', variant);
      fetch(root.dataset.compileUrl, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf,
                  'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.toString(),
      }).then(function (r) {
        if (pending) return null;  // код уже изменился — результат устарел
        if (r.ok) return r.blob().then(function (blob) {
          currentUrl = URL.createObjectURL(blob);
          builtKey = inFlightKey;
          // navpanes=0 прячет боковую панель миниатюр страниц во встроенном
          // просмотрщике (как в Adobe Acrobat по умолчанию)
          preview.ready(currentUrl + '#navpanes=0&view=FitH');
          download.href = currentUrl;
          download.hidden = false;
          refreshStale();
          if (window.EgorAutosave) window.EgorAutosave.showSaved(true, 'PDF собран ✓');
        });
        return r.json().then(function (data) {
          var message = data.message || 'Ошибка компиляции';
          preview.error(message);
          status.textContent = message;
          if (data.log) {
            log.textContent = data.log;
            log.hidden = false;
          }
        });
      }).catch(function () {
        if (!pending) preview.error('Нет связи с сервером');
      }).finally(function () {
        inFlight = false;
        if (pending) {
          pending = false;
          compile();
        }
      });
    }

    // --- Вариант: другой исходный код, оформление переносится ---
    function switchVariant(value) {
      if (value === variant || !variants[value]) return;
      if (editedByHand && !window.confirm(
          'Ручные правки кода пропадут: код заменится на вариант «'
          + variants[value].label + '». Переключить?')) return;
      var options = readOptions(source.value);
      variant = value;
      root.dataset.variant = value;
      original.value = variants[value].tex;
      var tex = variants[value].tex;
      Object.keys(options).forEach(function (kind) {
        tex = applyOption(tex, kind, options[kind]);
      });
      source.value = tex;
      editedByHand = false;
      root.dataset.filename = variants[value].filename;
      download.setAttribute('download', variants[value].filename);
      var url = new URL(window.location.href);
      url.searchParams.set('variant', value);
      window.history.replaceState(null, '', url);
    }

    // --- Быстрые переключатели: типовые правки кода ---
    function applySwitch(kind, value) {
      if (kind === 'variant') {
        switchVariant(value);
      } else {
        source.value = applyOption(source.value, kind, value);
      }
      markActive();
      refreshStale();
    }

    function markActive() {
      var current = readOptions(source.value);
      current.variant = variant;
      document.querySelectorAll('.switch-group').forEach(function (group) {
        group.querySelectorAll('button').forEach(function (btn) {
          var active = btn.dataset.value === current[group.dataset.switch];
          btn.classList.toggle('is-active', active);
          btn.setAttribute('aria-pressed', String(active));
        });
      });
    }

    document.querySelectorAll('.switch-group button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        applySwitch(btn.closest('.switch-group').dataset.switch,
                    btn.dataset.value);
      });
    });

    source.addEventListener('input', function () {
      editedByHand = true;
      markActive();
      refreshStale();
    });
    compileButtons.forEach(function (btn) {
      btn.addEventListener('click', compile);
    });
    document.getElementById('reset-btn').addEventListener('click', function () {
      source.value = original.value;
      editedByHand = false;
      markActive();
      refreshStale();
    });

    markActive();
  });
})();
