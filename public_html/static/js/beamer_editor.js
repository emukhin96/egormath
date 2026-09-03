/* Split-редактор презентации: слева Beamer-tex, справа собранный PDF.
   Переключатели только запоминают выбор; сборка — отдельной кнопкой. */
(function () {
  'use strict';

  var DOC_RE = /\\documentclass(?:\[([^\]]*)\])?\{beamer\}/;
  var PKG_RE = /\\usepackage(?:\[([^\]]*)\])?\{egorbeamer\}/;

  function splitOpts(raw) {
    return (raw || '').split(',').map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function docOptions(tex) {
    return splitOpts((tex.match(DOC_RE) || [])[1]);
  }

  function pkgOptions(tex) {
    return splitOpts((tex.match(PKG_RE) || [])[1]);
  }

  function withDocOptions(tex, parts) {
    return tex.replace(DOC_RE, function () {
      return parts.length
        ? '\\documentclass[' + parts.join(',') + ']{beamer}'
        : '\\documentclass{beamer}';
    });
  }

  function withPkgOptions(tex, parts) {
    return tex.replace(PKG_RE, function () {
      return parts.length
        ? '\\usepackage[' + parts.join(',') + ']{egorbeamer}'
        : '\\usepackage{egorbeamer}';
    });
  }

  function setKeyed(parts, key, value) {
    var prefix = key + '=';
    var next = parts.filter(function (s) { return s.indexOf(prefix) !== 0; });
    next.push(prefix + value);
    return next;
  }

  function getKeyed(parts, key, fallback) {
    var prefix = key + '=';
    for (var i = 0; i < parts.length; i += 1) {
      if (parts[i].indexOf(prefix) === 0) return parts[i].slice(prefix.length);
    }
    return fallback;
  }

  function setFlag(parts, onName, offName, on) {
    var next = parts.filter(function (s) {
      return s !== onName && s !== offName;
    });
    next.push(on ? onName : offName);
    return next;
  }

  function getFlag(parts, onName) {
    return parts.indexOf(onName) !== -1 ? 'on' : 'off';
  }

  function getSize(parts) {
    for (var i = 0; i < parts.length; i += 1) {
      if (/^(11|12|14)pt$/.test(parts[i])) return parts[i];
    }
    return '12pt';
  }

  function setSize(parts, value) {
    var next = parts.filter(function (s) { return !/^(11|12|14)pt$/.test(s); });
    next.push(value);
    return next;
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
    var inFlight = false;
    var pendingCompile = false;
    var state = readState();

    function readState() {
      var doc = docOptions(source.value);
      var pkg = pkgOptions(source.value);
      var theme = getKeyed(pkg, 'theme', 'light');
      return {
        theme: theme === 'paper' ? 'light' : theme,
        aspect: getKeyed(doc, 'aspectratio', '169'),
        size: getSize(doc),
        content: getKeyed(pkg, 'content', 'problems'),
        reveal: getKeyed(pkg, 'reveal', 'click'),
        items: getKeyed(pkg, 'items', 'all'),
        itemflow: getKeyed(pkg, 'itemflow', 'stack'),
        font: getKeyed(pkg, 'font', 'school'),
        stars: getFlag(pkg, 'stars'),
        footer: getFlag(pkg, 'footer'),
      };
    }

    function writeState() {
      var tex = source.value;
      var doc = setKeyed(setSize(docOptions(tex), state.size),
                         'aspectratio', state.aspect);
      var pkg = pkgOptions(tex);
      pkg = setKeyed(pkg, 'theme', state.theme);
      pkg = setKeyed(pkg, 'content', state.content);
      pkg = setKeyed(pkg, 'reveal', state.reveal);
      pkg = setKeyed(pkg, 'items', state.items);
      pkg = setKeyed(pkg, 'itemflow', state.itemflow);
      pkg = setKeyed(pkg, 'font', state.font);
      pkg = setFlag(pkg, 'stars', 'nostars', state.stars === 'on');
      pkg = setFlag(pkg, 'footer', 'nofooter', state.footer === 'on');
      source.value = withPkgOptions(withDocOptions(tex, doc), pkg);
    }

    function clearResult() {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = null;
      frame.removeAttribute('src');
      download.hidden = true;
      download.removeAttribute('href');
    }

    function compile() {
      writeState();
      if (inFlight) {
        pendingCompile = true;
        status.textContent = 'Сборка…';
        return;
      }
      inFlight = true;
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
      }).then(function (r) {
        if (pendingCompile) return null;
        if (r.ok) return r.blob().then(function (blob) {
          currentUrl = URL.createObjectURL(blob);
          frame.src = currentUrl + '#navpanes=0&view=Fit';
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
        if (!pendingCompile) status.textContent = 'Нет связи с сервером';
      }).finally(function () {
        inFlight = false;
        if (pendingCompile) {
          pendingCompile = false;
          compile();
        }
      });
    }

    function markActive() {
      document.querySelectorAll('.switch-group').forEach(function (group) {
        group.querySelectorAll('button').forEach(function (btn) {
          btn.classList.toggle(
            'is-active', btn.dataset.value === state[group.dataset.switch]);
        });
      });
    }

    document.querySelectorAll('.switch-group button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state[btn.closest('.switch-group').dataset.switch] = btn.dataset.value;
        markActive();
      });
    });

    source.addEventListener('input', function () {
      state = readState();
      markActive();
    });

    document.getElementById('compile-btn').addEventListener('click', compile);
    var sidebarCompile = document.getElementById('sidebar-compile-btn');
    if (sidebarCompile) {
      sidebarCompile.addEventListener('click', compile);
    }
    document.getElementById('reset-btn').addEventListener('click', function () {
      source.value = original.value;
      state = readState();
      markActive();
    });

    markActive();
  });
})();
