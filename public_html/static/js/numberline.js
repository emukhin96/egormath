/* Числовая прямая для слота «промежуток» (range) в маске ответа.

   Разметка серверная (_mask.html): текстовое поле .mask-range и пустой
   контейнер [data-numberline="имя поля"] под ним. Скрипт рисует в контейнере
   SVG-прямую; ученик выделяет промежутки мышью или пальцем:
     - протянуть по прямой — новый промежуток (концы включены, ●);
     - тянуть за стрелку на краю — бесконечный конец;
     - клик по концу промежутка — включить/исключить точку (● / ○);
     - клик по телу промежутка — убрать его;
     - отпустить там же, где нажали, — одна точка [a; a].
   Каждое изменение записывает текст в поле («(-∞; -5) ∪ [1; 4)» — его же
   разбирает сервер) и шлёт change для автосохранения. Текст, набранный
   руками, разбирается обратно, если это скобочная запись или простые
   неравенства (x>5; 1<x<4); иначе прямая просто не меняется.
   Без JS остаётся текстовое поле. */
(function () {
  'use strict';

  var W = 340, H = 64, PAD = 22, AXIS_Y = 30;
  var STEPS = [0.25, 0.5, 1, 2, 5, 10, 20, 50, 100];
  var TICKS = 10; /* тиков в каждую сторону от нуля */

  function fmt(v) {
    if (v === -Infinity) return '-∞';
    if (v === Infinity) return '+∞';
    var s = String(Math.round(v * 1000) / 1000);
    return s.replace('.', ',');
  }

  function num(text) {
    text = text.trim().replace(',', '.').replace(/\\left|\\right/g, '');
    if (/^[-−]?\s*(∞|\\infty|inf)$/i.test(text)) return -Infinity;
    if (/^\+?\s*(∞|\\infty|inf)$/i.test(text)) return Infinity;
    var frac = text.match(/^(-?)\\frac\{(-?\d+(?:\.\d+)?)\}\{(\d+(?:\.\d+)?)\}$/);
    if (frac) return (frac[1] ? -1 : 1) * parseFloat(frac[2]) / parseFloat(frac[3]);
    var simple = text.match(/^(-?\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)$/);
    if (simple) return parseFloat(simple[1]) / parseFloat(simple[2]);
    if (/^-?\d+(?:\.\d+)?$/.test(text)) return parseFloat(text);
    return NaN;
  }

  /* Текст → список промежутков {lo, hi, lc, rc} или null, если не разобрано */
  function parse(text) {
    text = (text || '').replace(/\$/g, '').replace(/\\cup/g, '∪')
      .replace(/\\le(?:q|qslant)?\b/g, '<=').replace(/\\ge(?:q|qslant)?\b/g, '>=')
      .replace(/≤/g, '<=').replace(/≥/g, '>=').replace(/^\s*[a-zA-Zа-яА-Я]\s*(?:\\in|∈)\s*/, '')
      .trim();
    if (!text) return [];
    var out = [];
    var tokens = [];
    var rest = text.replace(/[(\[]\s*[^;()\[\]]+?\s*;\s*[^;()\[\]]+?\s*[)\]]/g, function (m) {
      tokens.push(m);
      return '\u0000' + (tokens.length - 1) + '\u0000';
    });
    var pieces = rest.split(/\s*(?:∪|,|;|\bили\b|\bor\b|\bи\b)\s*/);
    for (var i = 0; i < pieces.length; i++) {
      var piece = pieces[i].trim();
      if (!piece) continue;
      var ref = piece.match(/^\u0000(\d+)\u0000$/);
      var iv;
      if (ref) {
        iv = parseBracket(tokens[parseInt(ref[1], 10)]);
        if (!iv) return null;
        out.push(iv);
        continue;
      }
      var ivs = parseInequality(piece);
      if (!ivs) return null;
      out = out.concat(ivs);
    }
    return normalize(out);
  }

  function parseBracket(token) {
    var m = token.match(/^([(\[])\s*(.+?)\s*;\s*(.+?)\s*([)\]])$/);
    if (!m) return null;
    var lo = num(m[2]), hi = num(m[3]);
    if (isNaN(lo) || isNaN(hi)) return null;
    return {lo: lo, hi: hi, lc: m[1] === '[', rc: m[4] === ']'};
  }

  function parseInequality(piece) {
    var v = '[a-zA-Zа-яА-Я]';
    var chain = piece.match(new RegExp('^(.+?)\\s*(<=|>=|<|>)\\s*' + v + '\\s*(<=|>=|<|>)\\s*(.+)$'));
    if (chain) {
      if (chain[2][0] !== chain[3][0]) return null;
      var a = num(chain[1]), b = num(chain[4]);
      if (isNaN(a) || isNaN(b)) return null;
      var less = chain[2][0] === '<';
      return [{
        lo: less ? a : b, hi: less ? b : a,
        lc: (less ? chain[2] : chain[3]).length === 2,
        rc: (less ? chain[3] : chain[2]).length === 2,
      }];
    }
    var left = piece.match(new RegExp('^' + v + '\\s*(<=|>=|<|>)\\s*(.+)$'));
    var op, value;
    if (left) {
      op = left[1]; value = num(left[2]);
    } else {
      var right = piece.match(new RegExp('^(.+?)\\s*(<=|>=|<|>)\\s*' + v + '$'));
      if (!right) return null;
      value = num(right[1]);
      op = {'<': '>', '<=': '>=', '>': '<', '>=': '<='}[right[2]];
    }
    if (isNaN(value)) return null;
    if (op[0] === '>') return [{lo: value, hi: Infinity, lc: op.length === 2, rc: false}];
    return [{lo: -Infinity, hi: value, lc: false, rc: op.length === 2}];
  }

  /* Убрать пустые, склеить пересекающиеся — как _normalize_intervals на сервере */
  function normalize(list) {
    var cleaned = list.filter(function (iv) {
      return !(iv.lo > iv.hi || (iv.lo === iv.hi && (!iv.lc || !iv.rc)));
    }).map(function (iv) {
      return {lo: iv.lo, hi: iv.hi,
              lc: iv.lo === -Infinity ? false : iv.lc,
              rc: iv.hi === Infinity ? false : iv.rc};
    });
    cleaned.sort(function (a, b) { return a.lo - b.lo || (b.lc - a.lc) || a.hi - b.hi; });
    var merged = [];
    cleaned.forEach(function (cur) {
      var last = merged[merged.length - 1];
      if (last && (cur.lo < last.hi || (cur.lo === last.hi && (last.rc || cur.lc)))) {
        if (cur.hi > last.hi || (cur.hi === last.hi && cur.rc)) {
          last.hi = cur.hi; last.rc = cur.rc;
        }
        return;
      }
      merged.push(cur);
    });
    return merged;
  }

  function format(list) {
    return list.map(function (iv) {
      return (iv.lc ? '[' : '(') + fmt(iv.lo) + '; ' + fmt(iv.hi) + (iv.rc ? ']' : ')');
    }).join(' ∪ ');
  }

  function svgEl(name, attrs) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  function NumberLine(container, input) {
    this.container = container;
    this.input = input;
    this.intervals = [];
    this.step = 1;
    this.drag = null;
    this.build();
    this.fromText();
    this.render();
  }

  NumberLine.prototype.build = function () {
    var self = this;
    this.svg = svgEl('svg', {viewBox: '0 0 ' + W + ' ' + H, width: W, height: H,
                             'class': 'numberline-svg', role: 'img'});
    this.svg.setAttribute('aria-label', 'Числовая прямая: протяните мышью, чтобы отметить промежуток');
    this.container.appendChild(this.svg);

    var tools = document.createElement('span');
    tools.className = 'numberline-tools';
    this.zoomOut = this.tool(tools, '−', 'Крупнее шаг', function () { self.zoom(1); });
    this.stepLabel = document.createElement('span');
    this.stepLabel.className = 'numberline-step';
    tools.appendChild(this.stepLabel);
    this.zoomIn = this.tool(tools, '+', 'Мельче шаг', function () { self.zoom(-1); });
    this.tool(tools, 'очистить', 'Убрать все промежутки', function () {
      self.intervals = [];
      self.commit();
    });
    this.container.appendChild(tools);

    this.svg.addEventListener('pointerdown', function (e) { self.onDown(e); });
    this.svg.addEventListener('pointermove', function (e) { self.onMove(e); });
    this.svg.addEventListener('pointerup', function (e) { self.onUp(e); });
    this.svg.addEventListener('pointercancel', function () { self.drag = null; self.render(); });
    this.input.addEventListener('input', function () { self.fromText(); self.render(); });
  };

  NumberLine.prototype.tool = function (parent, text, title, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'numberline-btn';
    b.textContent = text;
    b.title = title;
    b.addEventListener('click', onClick);
    parent.appendChild(b);
    return b;
  };

  NumberLine.prototype.zoom = function (dir) {
    var i = STEPS.indexOf(this.step) + dir;
    if (i < 0 || i >= STEPS.length) return;
    this.step = STEPS[i];
    this.render();
  };

  /* Шаг сетки такой, чтобы все конечные концы попали в окно ±TICKS шагов */
  NumberLine.prototype.fitStep = function () {
    var maxAbs = 0;
    this.intervals.forEach(function (iv) {
      [iv.lo, iv.hi].forEach(function (v) {
        if (isFinite(v)) maxAbs = Math.max(maxAbs, Math.abs(v));
      });
    });
    for (var i = 0; i < STEPS.length; i++) {
      if (maxAbs <= STEPS[i] * TICKS) { this.step = Math.max(this.step, STEPS[i]); return; }
    }
    this.step = STEPS[STEPS.length - 1];
  };

  NumberLine.prototype.x = function (v) {
    var range = this.step * TICKS;
    if (v === -Infinity) return 4;
    if (v === Infinity) return W - 4;
    return PAD + (v + range) / (2 * range) * (W - 2 * PAD);
  };

  /* Пиксель → значение с привязкой к полушагу; за краями оси — бесконечность */
  NumberLine.prototype.value = function (px) {
    if (px < PAD - 6) return -Infinity;
    if (px > W - PAD + 6) return Infinity;
    var range = this.step * TICKS;
    var v = (px - PAD) / (W - 2 * PAD) * 2 * range - range;
    var half = this.step / 2;
    v = Math.round(v / half) * half;
    return Math.max(-range, Math.min(range, v));
  };

  NumberLine.prototype.px = function (e) {
    var rect = this.svg.getBoundingClientRect();
    return (e.clientX - rect.left) / rect.width * W;
  };

  NumberLine.prototype.fromText = function () {
    var parsed = parse(this.input.value);
    if (parsed === null) return;
    this.intervals = parsed;
    this.fitStep();
  };

  NumberLine.prototype.commit = function () {
    this.intervals = normalize(this.intervals);
    this.input.value = format(this.intervals);
    this.input.dispatchEvent(new Event('change', {bubbles: true}));
    this.render();
  };

  NumberLine.prototype.onDown = function (e) {
    if (e.button && e.button !== 0) return;
    var target = e.target;
    var px = this.px(e);
    if (target.dataset && target.dataset.end) {
      /* Клик по концу — включить/исключить точку */
      var iv = this.intervals[parseInt(target.dataset.iv, 10)];
      if (target.dataset.end === 'lo' && isFinite(iv.lo)) iv.lc = !iv.lc;
      if (target.dataset.end === 'hi' && isFinite(iv.hi)) iv.rc = !iv.rc;
      if (iv.lo === iv.hi && (!iv.lc || !iv.rc)) this.intervals.splice(this.intervals.indexOf(iv), 1);
      this.commit();
      return;
    }
    this.drag = {start: this.value(px), cur: this.value(px), startPx: px,
                 body: target.dataset && target.dataset.body !== undefined ? parseInt(target.dataset.body, 10) : null};
    this.svg.setPointerCapture(e.pointerId);
    this.render();
  };

  NumberLine.prototype.onMove = function (e) {
    if (!this.drag) return;
    this.drag.cur = this.value(this.px(e));
    this.render();
  };

  NumberLine.prototype.onUp = function (e) {
    if (!this.drag) return;
    var d = this.drag;
    this.drag = null;
    var moved = Math.abs(this.px(e) - d.startPx) > 4;
    if (!moved && d.body !== null) {
      /* Клик по телу промежутка — убрать */
      this.intervals.splice(d.body, 1);
      this.commit();
      return;
    }
    var a = d.start, b = this.value(this.px(e));
    if (a === -Infinity && b === -Infinity || a === Infinity && b === Infinity) { this.render(); return; }
    var lo = Math.min(a, b), hi = Math.max(a, b);
    this.intervals.push({lo: lo, hi: hi, lc: isFinite(lo), rc: isFinite(hi)});
    this.commit();
  };

  NumberLine.prototype.render = function () {
    var svg = this.svg;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var self = this;
    var range = this.step * TICKS;

    /* Ось со стрелками */
    svg.appendChild(svgEl('line', {x1: 2, y1: AXIS_Y, x2: W - 2, y2: AXIS_Y, 'class': 'nl-axis'}));
    svg.appendChild(svgEl('path', {d: 'M' + (W - 2) + ',' + AXIS_Y + ' l-7,-4 v8 z', 'class': 'nl-arrow'}));
    svg.appendChild(svgEl('path', {d: 'M2,' + AXIS_Y + ' l7,-4 v8 z', 'class': 'nl-arrow'}));

    for (var k = -TICKS; k <= TICKS; k++) {
      var v = k * this.step;
      var x = this.x(v);
      svg.appendChild(svgEl('line', {x1: x, y1: AXIS_Y - (k === 0 ? 7 : 4), x2: x, y2: AXIS_Y + (k === 0 ? 7 : 4), 'class': 'nl-tick'}));
      if (k % 2 === 0 || TICKS <= 5) {
        var label = svgEl('text', {x: x, y: AXIS_Y + 20, 'class': 'nl-label', 'text-anchor': 'middle'});
        label.textContent = fmt(v);
        svg.appendChild(label);
      }
    }

    /* Промежутки: тело, затем концы (концы поверх тела, чтобы ловить клики) */
    var list = this.intervals.slice();
    if (this.drag) {
      var a = this.drag.start, b = this.drag.cur;
      list.push({lo: Math.min(a, b), hi: Math.max(a, b), lc: true, rc: true, preview: true});
    }
    list.forEach(function (iv, i) {
      var x1 = self.x(iv.lo), x2 = self.x(iv.hi);
      var body = svgEl('line', {x1: x1, y1: AXIS_Y, x2: x2, y2: AXIS_Y,
                                 'class': 'nl-body' + (iv.preview ? ' nl-preview' : '')});
      if (!iv.preview) body.dataset.body = i;
      svg.appendChild(body);
      /* Широкая невидимая зона над телом — удобнее кликать */
      if (!iv.preview) {
        var hit = svgEl('line', {x1: x1, y1: AXIS_Y, x2: x2, y2: AXIS_Y, 'class': 'nl-hit'});
        hit.dataset.body = i;
        svg.appendChild(hit);
      }
    });
    list.forEach(function (iv, i) {
      if (iv.preview) return;
      [['lo', iv.lo, iv.lc], ['hi', iv.hi, iv.rc]].forEach(function (end) {
        if (!isFinite(end[1])) return;
        var c = svgEl('circle', {cx: self.x(end[1]), cy: AXIS_Y, r: 6,
                                 'class': 'nl-end ' + (end[2] ? 'nl-closed' : 'nl-open')});
        c.dataset.iv = i;
        c.dataset.end = end[0];
        c.appendChild(svgEl('title')).textContent =
          fmt(end[1]) + (end[2] ? ' включено — нажмите, чтобы исключить' : ' исключено — нажмите, чтобы включить');
        svg.appendChild(c);
      });
    });
    this.stepLabel.textContent = 'шаг ' + fmt(this.step);
    this.zoomOut.disabled = this.step === STEPS[STEPS.length - 1];
    this.zoomIn.disabled = this.step === STEPS[0];
  };

  function init(root) {
    root.querySelectorAll('[data-numberline]').forEach(function (container) {
      if (container.dataset.ready) return;
      var form = container.closest('form') || document;
      var input = form.querySelector('input[name="' + container.dataset.numberline + '"]')
        || document.querySelector('input[name="' + container.dataset.numberline + '"]');
      if (!input) return;
      container.dataset.ready = '1';
      new NumberLine(container, input);
    });
  }

  document.addEventListener('DOMContentLoaded', function () { init(document); });
  window.EgorNumberLine = {init: init, parse: parse, format: format};
})();
