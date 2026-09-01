/* Split-редактор презентации: слева Beamer-tex, справа собранный PDF.
   Переключатели правят опции documentclass / egorbeamer и пересобирают. */
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
    var pending = false;

    function clearResult() {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = null;
      frame.removeAttribute('src');
      download.hidden = true;
      download.removeAttribute('href');
    }

    function compile() {
      if (inFlight) {
        pending = true;
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
        if (pending) return null;
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
        if (!pending) status.textContent = 'Нет связи с сервером';
      }).finally(function () {
        inFlight = false;
        if (pending) {
          pending = false;
          compile();
        }
      });
    }

    function applySwitch(kind, value) {
      var tex = source.value;
      var doc = docOptions(tex);
      var pkg = pkgOptions(tex);
      if (kind === 'size') {
        tex = withDocOptions(tex, setSize(doc, value));
      } else if (kind === 'aspect') {
        tex = withDocOptions(tex, setKeyed(doc, 'aspectratio', value));
      } else if (kind === 'theme') {
        tex = withPkgOptions(tex, setKeyed(pkg, 'theme', value));
      } else if (kind === 'content') {
        tex = withPkgOptions(tex, setKeyed(pkg, 'content', value));
      } else if (kind === 'reveal') {
        tex = withPkgOptions(tex, setKeyed(pkg, 'reveal', value));
      } else if (kind === 'stars') {
        tex = withPkgOptions(tex, setFlag(pkg, 'stars', 'nostars', value === 'on'));
      } else if (kind === 'footer') {
        tex = withPkgOptions(tex, setFlag(pkg, 'footer', 'nofooter', value === 'on'));
      }
      source.value = tex;
      markActive();
      compile();
    }

    function markActive() {
      var doc = docOptions(source.value);
      var pkg = pkgOptions(source.value);
      var current = {
        theme: getKeyed(pkg, 'theme', 'light'),
        aspect: getKeyed(doc, 'aspectratio', '169'),
        size: getSize(doc),
        content: getKeyed(pkg, 'content', 'problems'),
        reveal: getKeyed(pkg, 'reveal', 'click'),
        stars: getFlag(pkg, 'stars'),
        footer: getFlag(pkg, 'footer'),
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
