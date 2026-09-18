/* Холст — векторная мини-доска к задаче (приложение canvas).

   Разметка серверная: <div data-canvas data-url="…" data-role="student|teacher|viewer"
   data-pages="N">. Скрипт сам строит панель инструментов и грузит страницы JSON.

   Истина — список элементов слоя ({id, t, c, w, p, g?, k?}), кадр перерисовывается
   целиком; элементы неизменяемы — любая правка создаёт новый объект с тем же id,
   поэтому отмена/возврат — это просто пара «список до / список после».
   Координаты логические: страница 1000×750 при любой ширине экрана.

   Слои: ученик пишет в student, учитель — в teacher; чужой слой рисуется
   подложкой и недоступен ластику/выделению. Сохранение — через 1 с после
   последнего изменения (не реже раза в 5 с при непрерывном письме), очередь
   и тост — общие с автосохранением ответов (EgorAutosave). */
(function () {
  'use strict';

  var W = 1000, H = 750;
  var COLORS = ['#111827', '#1d4ed8', '#dc2626', '#16a34a', '#ea580c', '#7c3aed'];
  var HL_COLORS = ['#facc15', '#4ade80', '#f472b6', '#38bdf8'];
  var PEN_WIDTHS = [2, 4, 7], HL_WIDTHS = [12, 20, 30], ERASER_SIZES = [10, 25, 50];
  var HL_ALPHA = 0.35, HIT_TOL = 8, MAX_UNDO = 100;
  var DEBOUNCE = 1000, MAX_WAIT = 5000, RETRY = [3000, 10000, 30000], KEEPALIVE_LIMIT = 60000;
  var SHOW_KEY = 'canvas-show';
  var GRID_COLOR = '#d4d4d8', ACCENT = '#1765b5';
  var CELLS = {grid: 25, grid_large: 50};
  var FN = {
    parabola: {label: 'x²', title: 'Парабола y = x²', f: function (x) { return x * x; }},
    abs: {label: '|x|', title: 'Модуль y = |x|', f: function (x) { return Math.abs(x); }},
    sqrt: {label: '√x', title: 'Корень y = √x', f: function (x) { return x < 0 ? NaN : Math.sqrt(x); }},
    hyperbola: {label: '1/x', title: 'Гипербола y = 1/x', f: function (x) { return x === 0 ? NaN : 1 / x; }},
  };
  var SHAPE_TOOLS = {
    line: {label: '—', title: 'Отрезок (L)'}, dot: {label: '•', title: 'Точка'},
    circle: {label: '○', title: 'Окружность: центр и радиус'}, rect: {label: '▭', title: 'Прямоугольник'},
    square: {label: '□', title: 'Квадрат'}, tri: {label: '△', title: 'Треугольник: три клика'},
    para: {label: '▱', title: 'Параллелограмм: три клика'},
  };
  var BG_LABELS = {blank: 'Белый', grid: 'Клетка', grid_large: 'Крупная клетка', plane: 'Координатная плоскость'};

  /* ---------- утилиты ---------- */

  function uid() { return Math.random().toString(36).slice(2, 10); }
  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) EgorAutosave.showSaved(ok, message);
  }
  function csrfToken() {
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function button(cls, text, title, onclick) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (title) b.title = title;
    if (onclick) b.addEventListener('click', onclick);
    return b;
  }
  function dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1]); }
  function distToSegment(c, a, b) {
    var dx = b[0] - a[0], dy = b[1] - a[1], len2 = dx * dx + dy * dy;
    var t = len2 ? Math.max(0, Math.min(1, ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / len2)) : 0;
    return Math.hypot(c[0] - (a[0] + t * dx), c[1] - (a[1] + t * dy));
  }
  /* Дуглас–Пойкер: штрих стилусом ужимается в 3–5 раз без видимой потери */
  function simplify(points, tol) {
    if (points.length < 3) return points;
    var keep = new Uint8Array(points.length);
    keep[0] = keep[points.length - 1] = 1;
    var stack = [[0, points.length - 1]];
    while (stack.length) {
      var seg = stack.pop(), a = seg[0], b = seg[1], best = -1, bestD = tol;
      for (var i = a + 1; i < b; i++) {
        var d = distToSegment(points[i], points[a], points[b]);
        if (d > bestD) { bestD = d; best = i; }
      }
      if (best > 0) { keep[best] = 1; stack.push([a, best], [best, b]); }
    }
    var out = [];
    for (var j = 0; j < points.length; j++) if (keep[j]) out.push(points[j]);
    return out;
  }
  function roundPoint(p) { return [Math.round(p[0]), Math.round(p[1])]; }
  function shifted(element, dx, dy) {
    var copy = Object.assign({}, element);
    copy.p = element.p.map(function (p) { return [Math.round(p[0] + dx), Math.round(p[1] + dy)]; });
    return copy;
  }

  /* ---------- геометрия элементов ---------- */

  var polyCache = new WeakMap();

  function fnPolylines(element) {
    var cached = polyCache.get(element);
    if (cached) return cached;
    var o = element.p[0], h = element.p[1];
    var sx = h[0] - o[0], sy = o[1] - h[1];
    if (Math.abs(sx) < 1) sx = sx < 0 ? -1 : 1;
    if (Math.abs(sy) < 1) sy = sy < 0 ? -1 : 1;
    var f = FN[element.k].f, lines = [], current = [];
    for (var px = -60; px <= W + 60; px += 3) {
      var x = (px - o[0]) / sx, y = f(x);
      var py = isFinite(y) ? o[1] - sy * y : NaN;
      if (isNaN(py) || py < -3000 || py > H + 3000) {
        if (current.length > 1) lines.push(current);
        current = [];
        continue;
      }
      current.push([px, py]);
    }
    if (current.length > 1) lines.push(current);
    polyCache.set(element, lines);
    return lines;
  }

  function polygonOf(element) {
    var p = element.p;
    switch (element.t) {
      case 'rect': return [[p[0][0], p[0][1]], [p[1][0], p[0][1]], [p[1][0], p[1][1]], [p[0][0], p[1][1]]];
      case 'tri': return [p[0], p[1], p[2]];
      case 'para': return [p[0], p[1], p[2], [p[0][0] + p[2][0] - p[1][0], p[0][1] + p[2][1] - p[1][1]]];
    }
    return null;
  }

  /* Ломаные для попадания курсора: у замкнутых фигур — контур с возвратом */
  function outlines(element) {
    var p = element.p;
    switch (element.t) {
      case 'path': case 'hl': case 'line': return [p];
      case 'dot': return [[p[0]]];
      case 'circle': {
        var r = dist(p[0], p[1]), pts = [];
        for (var i = 0; i <= 36; i++) {
          var a = i / 36 * Math.PI * 2;
          pts.push([p[0][0] + r * Math.cos(a), p[0][1] + r * Math.sin(a)]);
        }
        return [pts];
      }
      case 'fn': return fnPolylines(element);
      default: {
        var poly = polygonOf(element);
        return poly ? [poly.concat([poly[0]])] : [p];
      }
    }
  }

  function bbox(element) {
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    outlines(element).forEach(function (line) {
      line.forEach(function (pt) {
        if (pt[0] < minX) minX = pt[0]; if (pt[0] > maxX) maxX = pt[0];
        if (pt[1] < minY) minY = pt[1]; if (pt[1] > maxY) maxY = pt[1];
      });
    });
    var pad = element.w / 2;
    return [minX - pad, minY - pad, maxX + pad, maxY + pad];
  }

  function hits(element, pt, tol) {
    var box = bbox(element);
    if (pt[0] < box[0] - tol || pt[0] > box[2] + tol || pt[1] < box[1] - tol || pt[1] > box[3] + tol) return false;
    var limit = tol + element.w / 2;
    var lines = outlines(element);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (line.length === 1) { if (dist(line[0], pt) <= limit + 3) return true; continue; }
      for (var j = 0; j + 1 < line.length; j++) {
        if (distToSegment(pt, line[j], line[j + 1]) <= limit) return true;
      }
    }
    return false;
  }

  function insideBox(element, box) {
    var b = bbox(element);
    return b[0] >= box[0] && b[2] <= box[2] && b[1] >= box[1] && b[3] <= box[3];
  }

  /* Ластик: круг радиуса r вырезает участок ломаной точно по пересечениям
     с отрезками, поэтому быстрый штрих из двух точек тоже стирается посередине */
  function eraseFromPath(element, c, r) {
    var limit = r + element.w / 2, p = element.p, changed = false;
    if (p.length === 1) return dist(p[0], c) <= limit ? [] : null;
    var pieces = [], current = [];
    function inside(pt) { return dist(pt, c) <= limit; }
    function flush() { if (current.length >= 2) pieces.push(current); current = []; }
    for (var i = 0; i < p.length; i++) {
      var pt = p[i];
      if (i > 0) {
        var a = p[i - 1], hitsSeg = distToSegment(c, a, pt) <= limit;
        if (hitsSeg) {
          changed = true;
          var dx = pt[0] - a[0], dy = pt[1] - a[1], fx = a[0] - c[0], fy = a[1] - c[1];
          var A = dx * dx + dy * dy, B = 2 * (fx * dx + fy * dy), C = fx * fx + fy * fy - limit * limit;
          var D = B * B - 4 * A * C;
          if (A > 0 && D >= 0) {
            var sq = Math.sqrt(D), t1 = (-B - sq) / (2 * A), t2 = (-B + sq) / (2 * A);
            if (t1 > 0 && t1 < 1 && !inside(a)) current.push([a[0] + dx * t1, a[1] + dy * t1]);
            flush();
            if (t2 > 0 && t2 < 1 && !inside(pt)) current.push([a[0] + dx * t2, a[1] + dy * t2]);
          } else {
            flush();
          }
        }
      }
      if (!inside(pt)) current.push(pt); else changed = true;
    }
    flush();
    if (!changed) return null;
    return pieces.map(function (points, index) {
      var copy = Object.assign({}, element);
      copy.id = index === 0 ? element.id : uid();
      copy.p = points.map(roundPoint);
      return copy;
    });
  }

  /* ---------- рендер ---------- */

  function planeOrigin(page) {
    var cell = page.bgOptions.cell || 25;
    if (page.bgOptions.origin === 'bottom_left') return [cell * 2, H - cell * 2];
    return [W / 2, Math.round(H / 2 / cell) * cell];
  }
  function cellOf(page) {
    if (page.background === 'plane') return page.bgOptions.cell || 25;
    return CELLS[page.background] || 0;
  }

  function drawBackground(ctx, page) {
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);
    var cell = cellOf(page);
    if (!cell) return;
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var x = 0; x <= W; x += cell) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (var y = 0; y <= H; y += cell) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
    if (page.background !== 'plane') return;
    var o = planeOrigin(page);
    ctx.strokeStyle = '#111';
    ctx.fillStyle = '#111';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(0, o[1]); ctx.lineTo(W, o[1]);
    ctx.moveTo(o[0], H); ctx.lineTo(o[0], 0);
    /* единичные отметки, как в образцах xoy */
    ctx.moveTo(o[0] + cell, o[1] - 5); ctx.lineTo(o[0] + cell, o[1] + 5);
    ctx.moveTo(o[0] - 5, o[1] - cell); ctx.lineTo(o[0] + 5, o[1] - cell);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(W, o[1]); ctx.lineTo(W - 14, o[1] - 5); ctx.lineTo(W - 14, o[1] + 5); ctx.closePath();
    ctx.moveTo(o[0], 0); ctx.lineTo(o[0] - 5, 14); ctx.lineTo(o[0] + 5, 14); ctx.closePath();
    ctx.fill();
    ctx.font = 'italic 20px "Times New Roman", serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('x', W - 12, o[1] + 8);
    ctx.textAlign = 'left';
    ctx.fillText('y', o[0] + 10, 2);
    ctx.font = '16px "Times New Roman", serif';
    ctx.textAlign = 'center';
    ctx.fillText('1', o[0] + cell, o[1] + 7);
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText('1', o[0] - 7, o[1] - cell);
  }

  function tracePath(ctx, points) {
    ctx.moveTo(points[0][0], points[0][1]);
    if (points.length === 2) { ctx.lineTo(points[1][0], points[1][1]); return; }
    for (var i = 1; i + 1 < points.length; i++) {
      var mx = (points[i][0] + points[i + 1][0]) / 2, my = (points[i][1] + points[i + 1][1]) / 2;
      ctx.quadraticCurveTo(points[i][0], points[i][1], mx, my);
    }
    var last = points[points.length - 1];
    ctx.lineTo(last[0], last[1]);
  }

  function drawElement(ctx, element, page, dimmed) {
    var p = element.p;
    ctx.save();
    ctx.strokeStyle = element.c;
    ctx.fillStyle = element.c;
    ctx.lineWidth = element.w;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    if (dimmed) ctx.globalAlpha = 0.45;
    switch (element.t) {
      case 'path':
      case 'hl':
        if (element.t === 'hl') { ctx.globalAlpha *= HL_ALPHA; ctx.lineCap = 'butt'; }
        if (p.length === 1) {
          ctx.beginPath(); ctx.arc(p[0][0], p[0][1], element.w / 2, 0, Math.PI * 2); ctx.fill();
        } else {
          ctx.beginPath(); tracePath(ctx, p); ctx.stroke();
        }
        break;
      case 'line':
        ctx.beginPath(); ctx.moveTo(p[0][0], p[0][1]); ctx.lineTo(p[1][0], p[1][1]); ctx.stroke();
        break;
      case 'dot': {
        var r = Math.max(3, element.w);
        ctx.beginPath(); ctx.arc(p[0][0], p[0][1], r, 0, Math.PI * 2); ctx.fill();
        if (element.l && page.background === 'plane') {
          var o = planeOrigin(page), cell = cellOf(page);
          var x = (p[0][0] - o[0]) / cell, y = (o[1] - p[0][1]) / cell;
          var fmt = function (v) { return (Math.round(v * 10) / 10).toString().replace('.', ','); };
          ctx.font = '15px "Times New Roman", serif';
          ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
          ctx.fillText('(' + fmt(x) + '; ' + fmt(y) + ')', p[0][0] + r + 3, p[0][1] - r);
        }
        break;
      }
      case 'circle':
        ctx.beginPath(); ctx.arc(p[0][0], p[0][1], dist(p[0], p[1]), 0, Math.PI * 2); ctx.stroke();
        break;
      case 'fn':
        ctx.beginPath();
        fnPolylines(element).forEach(function (line) {
          ctx.moveTo(line[0][0], line[0][1]);
          for (var i = 1; i < line.length; i++) ctx.lineTo(line[i][0], line[i][1]);
        });
        ctx.stroke();
        break;
      default: {
        var poly = polygonOf(element);
        if (poly) {
          ctx.beginPath();
          ctx.moveTo(poly[0][0], poly[0][1]);
          for (var k = 1; k < poly.length; k++) ctx.lineTo(poly[k][0], poly[k][1]);
          ctx.closePath(); ctx.stroke();
        }
      }
    }
    ctx.restore();
  }

  /* ---------- виджет ---------- */

  function Widget(root) {
    this.root = root;
    this.url = root.dataset.url;
    this.role = root.dataset.role || 'viewer';
    this.pages = [];
    this.index = 0;
    this.layer = null;          /* слой, который можно править, или null */
    this.showTeacher = true;
    this.tool = this.role === 'teacher' ? 'pen' : 'pen';
    this.color = this.role === 'teacher' ? '#dc2626' : '#1d4ed8';
    this.hlColor = HL_COLORS[0];
    this.penWidth = PEN_WIDTHS[1];
    this.hlWidth = HL_WIDTHS[1];
    this.eraserSize = ERASER_SIZES[1];
    this.snap = false;
    this.selection = [];
    this.drag = null;
    this.pending = [];          /* точки недостроенной фигуры (треугольник, параллелограмм) */
    this.loaded = false;
    this.built = false;
    root.canvasWidget = this;
    root.classList.add('canvas-widget');
    var count = parseInt(root.dataset.pages || '0', 10) || 0;
    root.dataset.nonempty = count ? '1' : '';
    if (this.role === 'student') {
      if (count) this.show();
      else this.renderLauncher();
    } else {
      this.applyTeacherToggle();
    }
  }

  Widget.prototype.renderLauncher = function () {
    var self = this;
    this.root.innerHTML = '';
    var wrap = el('div', 'canvas-launch');
    wrap.appendChild(button('btn btn-small btn-secondary', 'Холст', 'Написать решение от руки', function () {
      self.show(true);
    }));
    this.root.appendChild(wrap);
  };

  Widget.prototype.applyTeacherToggle = function () {
    var on = false;
    try { on = localStorage.getItem(SHOW_KEY) === '1'; } catch (e) {}
    if (on) { this.show(); return; }
    this.built = false;
    this.root.innerHTML = '';
    var count = parseInt(this.root.dataset.pages || '0', 10) || 0;
    var note = el('p', 'helptext canvas-launch',
      count ? 'Холст: страниц — ' + count + '. Включите «Показать холсты», чтобы увидеть.'
            : 'Холста нет. Включите «Показать холсты», чтобы оставить пометки от руки.');
    this.root.appendChild(note);
  };

  Widget.prototype.show = function (createFirst) {
    var self = this;
    if (this.loaded) { this.build(); return; }
    fetch(this.url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.json().then(function (data) { return {status: r.status, data: data}; }); })
      .then(function (result) {
        if (!result.data || !result.data.ok) throw new Error(result.data && result.data.message || 'Не удалось загрузить холст');
        self.applyData(result.data);
        self.loaded = true;
        if (!self.pages.length && createFirst && self.layer) self.addPage();
        self.build();
      })
      .catch(function (error) { toast(false, error.message || 'Не удалось загрузить холст'); });
  };

  Widget.prototype.applyData = function (data) {
    var self = this;
    this.layer = data.layer;
    this.limits = data.limits || {student: 5, teacher: 2, total: 10, elements: 2000};
    this.showTeacherLayer = !!data.show_teacher_layer;
    this.pages = data.pages.map(function (raw) { return self.makePage(raw); });
    this.pages.forEach(function (page) { self.restoreBackup(page); });
    this.index = 0;
    this.updateNonEmpty();
  };

  Widget.prototype.makePage = function (raw) {
    return {
      number: raw.number,
      background: raw.background || 'grid',
      bgOptions: raw.background_options || {},
      locked: !!raw.locked,
      createdBy: raw.created_by_role || 'student',
      layers: {
        student: {elements: raw.student ? raw.student.elements : [], version: raw.student ? raw.student.version : 0},
        teacher: {elements: raw.teacher ? raw.teacher.elements : [], version: raw.teacher ? raw.teacher.version : 0},
      },
      undo: [], redo: [], dirty: false, saving: false, rev: 0, savedRev: 0, retry: 0, firstDirtyAt: 0, timer: null,
    };
  };

  Widget.prototype.editableLayer = function (page) {
    if (!this.layer) return null;
    if (this.layer === 'student' && page.locked) return null;
    return this.layer;
  };

  Widget.prototype.canAddPage = function () {
    if (!this.layer) return false;
    var pages = this.pages;
    if (pages.length >= this.limits.total) return false;
    if (this.layer === 'student') {
      return pages.filter(function (p) { return !p.locked && p.createdBy === 'student'; }).length < this.limits.student;
    }
    return pages.filter(function (p) { return p.createdBy === 'teacher'; }).length < this.limits.teacher;
  };

  Widget.prototype.addPage = function () {
    if (!this.canAddPage()) return;
    var previous = this.pages[this.pages.length - 1];
    var page = this.makePage({number: this.pages.length + 1, created_by_role: this.layer,
      background: previous ? previous.background : 'grid',
      background_options: previous ? previous.bgOptions : {}});
    this.pages.push(page);
    this.index = this.pages.length - 1;
    this.selection = [];
    this.pending = [];
    if (this.built) this.refresh();
  };

  Widget.prototype.removeLastPage = function () {
    var self = this, page = this.pages[this.pages.length - 1];
    if (!page || !this.editableLayer(page)) return;
    if (page.layers.student.elements.length || page.layers.teacher.elements.length) return;
    var finish = function () {
      self.pages.pop();
      self.index = Math.max(0, self.pages.length - 1);
      self.refresh();
    };
    var saved = page.layers.student.version || page.layers.teacher.version;
    if (!saved) { finish(); return; }
    fetch(this.url + page.number + '/delete/', {
      method: 'POST', credentials: 'same-origin',
      headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (data.ok) finish(); else toast(false, data.message || 'Не удалось удалить страницу');
    }).catch(function () { toast(false, 'Нет связи — страница не удалена'); });
  };

  /* ---------- DOM ---------- */

  Widget.prototype.build = function () {
    var self = this;
    if (this.built) { this.refresh(); return; }
    this.built = true;
    var root = this.root;
    root.innerHTML = '';
    this.head = el('div', 'canvas-head');
    this.toolbar = el('div', 'canvas-toolbar');
    this.stage = el('div', 'canvas-stage');
    this.base = el('canvas', 'canvas-base');
    this.top = el('canvas', 'canvas-top');
    this.stage.appendChild(this.base);
    this.stage.appendChild(this.top);
    root.appendChild(this.head);
    root.appendChild(this.toolbar);
    root.appendChild(this.stage);
    this.stage.addEventListener('pointerdown', function (e) { self.onDown(e); });
    this.stage.addEventListener('pointermove', function (e) { self.onMove(e); });
    this.stage.addEventListener('pointerup', function (e) { self.onUp(e); });
    this.stage.addEventListener('pointercancel', function (e) { self.onUp(e, true); });
    this.stage.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    root.addEventListener('pointerdown', function () { Widget.active = self; });
    if (window.ResizeObserver) {
      new ResizeObserver(function () { self.resize(); }).observe(this.stage);
    } else {
      window.addEventListener('resize', function () { self.resize(); });
    }
    this.refresh();
  };

  Widget.prototype.page = function () { return this.pages[this.index]; };

  /* Панель страниц, фон, слой учителя и инструменты — пересобираются при смене страницы */
  Widget.prototype.refresh = function () {
    var self = this, page = this.page();
    var head = this.head;
    head.innerHTML = '';
    var tabs = el('div', 'canvas-pages');
    tabs.appendChild(el('span', 'canvas-label', 'Холст'));
    this.pages.forEach(function (p, i) {
      var b = button('btn btn-small btn-secondary canvas-page', String(p.number),
        p.locked ? 'Страница отправлена — только просмотр' : 'Страница ' + p.number, function () {
          self.switchPage(i);
        });
      b.setAttribute('aria-pressed', String(i === self.index));
      if (p.locked) b.classList.add('canvas-page-locked');
      tabs.appendChild(b);
    });
    if (this.canAddPage()) {
      tabs.appendChild(button('btn btn-small btn-secondary', '+', 'Добавить страницу', function () { self.addPage(); }));
    }
    var last = this.pages[this.pages.length - 1];
    if (last && this.editableLayer(last) && !last.layers.student.elements.length && !last.layers.teacher.elements.length
        && (this.pages.length > 1 || this.role !== 'student')) {
      tabs.appendChild(button('icon-btn', '×', 'Удалить пустую последнюю страницу', function () { self.removeLastPage(); }));
    }
    head.appendChild(tabs);
    if (!page) {
      head.appendChild(el('span', 'helptext', this.layer ? 'Нажмите «+», чтобы добавить страницу.' : 'Страниц нет.'));
      this.toolbar.innerHTML = '';
      this.stage.hidden = true;
      return;
    }
    this.stage.hidden = false;
    var editable = this.editableLayer(page);

    var controls = el('div', 'canvas-controls');
    var bg = el('select', 'canvas-bg');
    Object.keys(BG_LABELS).forEach(function (key) {
      var opt = el('option', null, BG_LABELS[key]);
      opt.value = key;
      bg.appendChild(opt);
    });
    bg.value = page.background;
    bg.disabled = !editable;
    bg.title = 'Фон страницы';
    bg.addEventListener('change', function () {
      page.background = bg.value;
      if (bg.value === 'plane' && !page.bgOptions.cell) page.bgOptions = {cell: 25, origin: 'center'};
      self.touch(page);
      self.refresh();
    });
    controls.appendChild(bg);
    if (page.background === 'plane') {
      var cellSel = el('select', 'canvas-bg');
      [[25, 'мелкая клетка'], [50, 'крупная клетка']].forEach(function (pair) {
        var opt = el('option', null, pair[1]); opt.value = String(pair[0]); cellSel.appendChild(opt);
      });
      cellSel.value = String(page.bgOptions.cell || 25);
      cellSel.disabled = !editable;
      cellSel.addEventListener('change', function () {
        page.bgOptions = Object.assign({}, page.bgOptions, {cell: parseInt(cellSel.value, 10)});
        self.touch(page); self.redraw();
      });
      controls.appendChild(cellSel);
      var originSel = el('select', 'canvas-bg');
      [['center', 'начало в центре'], ['bottom_left', 'начало слева внизу']].forEach(function (pair) {
        var opt = el('option', null, pair[1]); opt.value = pair[0]; originSel.appendChild(opt);
      });
      originSel.value = page.bgOptions.origin || 'center';
      originSel.disabled = !editable;
      originSel.addEventListener('change', function () {
        page.bgOptions = Object.assign({}, page.bgOptions, {origin: originSel.value});
        self.touch(page); self.redraw();
      });
      controls.appendChild(originSel);
    }
    if (this.role === 'student' && this.showTeacherLayer) {
      controls.appendChild(this.toggle('Пометки учителя', this.showTeacher, function (on) {
        self.showTeacher = on; self.redraw();
      }));
    }
    if (page.locked && this.role === 'student') {
      controls.appendChild(el('span', 'helptext', 'Страница отправлена — только просмотр'));
    }
    head.appendChild(controls);

    this.buildToolbar(editable);
    this.selection = [];
    this.pending = [];
    this.resize();
  };

  Widget.prototype.toggle = function (text, checked, onchange) {
    var label = el('label', 'ws-toggle');
    var input = el('input'); input.type = 'checkbox'; input.checked = checked;
    input.addEventListener('change', function () { onchange(input.checked); });
    label.appendChild(input);
    label.appendChild(el('span', 'ws-toggle-slider'));
    label.appendChild(el('span', 'ws-toggle-text', text));
    return label;
  };

  Widget.prototype.buildToolbar = function (editable) {
    var self = this, bar = this.toolbar;
    bar.innerHTML = '';
    if (!editable) return;
    var page = this.page();
    function group(cls) { var g = el('div', 'canvas-group' + (cls ? ' ' + cls : '')); bar.appendChild(g); return g; }
    function tool(container, name, text, title) {
      var b = button('btn btn-small btn-secondary canvas-tool', text, title, function () { self.setTool(name); });
      b.dataset.tool = name;
      b.setAttribute('aria-pressed', String(self.tool === name));
      container.appendChild(b);
      return b;
    }
    var main = group();
    tool(main, 'pen', 'Карандаш', 'Карандаш (P)');
    tool(main, 'hl', 'Маркер', 'Выделитель (Shift+P)');
    tool(main, 'eraser', 'Ластик', 'Ластик: стирает карандаш и маркер (E)');
    tool(main, 'select', 'Выбор', 'Выделение и перемещение (V)');

    var shapes = group();
    Object.keys(SHAPE_TOOLS).forEach(function (name) { tool(shapes, name, SHAPE_TOOLS[name].label, SHAPE_TOOLS[name].title); });

    var graphs = group();
    Object.keys(FN).forEach(function (kind) {
      graphs.appendChild(button('btn btn-small btn-secondary canvas-tool', FN[kind].label, FN[kind].title + ' — вставить заготовку', function () {
        self.insertFn(kind);
      }));
    });

    var colors = group('canvas-colors');
    var palette = this.tool === 'hl' ? HL_COLORS : COLORS;
    var current = this.tool === 'hl' ? this.hlColor : this.color;
    palette.forEach(function (c) {
      var b = button('canvas-swatch', '', 'Цвет', function () {
        if (self.tool === 'hl') self.hlColor = c; else self.color = c;
        self.recolorSelection(c);
        self.buildToolbar(true);
      });
      b.style.setProperty('--c', c);
      b.setAttribute('aria-pressed', String(c === current));
      colors.appendChild(b);
    });

    var widths = group('canvas-widths');
    var sizes = this.tool === 'hl' ? HL_WIDTHS : this.tool === 'eraser' ? ERASER_SIZES : PEN_WIDTHS;
    var currentWidth = this.tool === 'hl' ? this.hlWidth : this.tool === 'eraser' ? this.eraserSize : this.penWidth;
    sizes.forEach(function (w, i) {
      var b = button('canvas-width', '', self.tool === 'eraser' ? 'Размер ластика' : 'Толщина', function () {
        if (self.tool === 'hl') self.hlWidth = w; else if (self.tool === 'eraser') self.eraserSize = w; else self.penWidth = w;
        self.buildToolbar(true);
      });
      var dot = el('span');
      dot.style.width = dot.style.height = (6 + i * 5) + 'px';
      b.appendChild(dot);
      b.setAttribute('aria-pressed', String(w === currentWidth));
      widths.appendChild(b);
    });

    var history = group();
    var undo = button('btn btn-small btn-secondary', '↶', 'Отменить (Ctrl+Z)', function () { self.undo(); });
    var redo = button('btn btn-small btn-secondary', '↷', 'Вернуть (Ctrl+Shift+Z)', function () { self.redo(); });
    undo.disabled = !page.undo.length;
    redo.disabled = !page.redo.length;
    history.appendChild(undo);
    history.appendChild(redo);
    this.undoButton = undo;
    this.redoButton = redo;

    var sel = group('canvas-selection');
    sel.hidden = !this.selection.length;
    sel.appendChild(button('btn btn-small btn-secondary', 'Удалить', 'Удалить выделенное (Delete)', function () { self.deleteSelection(); }));
    sel.appendChild(button('btn btn-small btn-secondary', 'Группа', 'Сгруппировать (Ctrl+G)', function () { self.groupSelection(true); }));
    sel.appendChild(button('btn btn-small btn-secondary', 'Разгруппировать', 'Разгруппировать (Ctrl+Shift+G)', function () { self.groupSelection(false); }));
    sel.appendChild(button('btn btn-small btn-secondary', 'Вперёд', 'На передний план (])', function () { self.reorderSelection(true); }));
    sel.appendChild(button('btn btn-small btn-secondary', 'Назад', 'На задний план ([)', function () { self.reorderSelection(false); }));
    this.selectionGroup = sel;

    var misc = group();
    misc.appendChild(button('btn btn-small btn-secondary', 'Очистить', 'Очистить страницу (можно отменить)', function () { self.clearPage(); }));
    if (cellOf(page)) {
      misc.appendChild(this.toggle('К сетке', this.snap, function (on) { self.snap = on; }));
    }
  };

  Widget.prototype.setTool = function (name) {
    this.tool = name;
    this.pending = [];
    if (name !== 'select') this.selection = [];
    this.buildToolbar(true);
    this.drawTop();
  };

  Widget.prototype.switchPage = function (i) {
    if (i === this.index) return;
    this.flush(this.page());
    this.index = i;
    this.refresh();
  };

  /* ---------- размеры и перерисовка ---------- */

  Widget.prototype.resize = function () {
    if (!this.stage || this.stage.hidden) return;
    var width = this.stage.clientWidth;
    if (!width) return;
    var height = Math.round(width * H / W), dpr = window.devicePixelRatio || 1;
    this.scale = width / W;
    [this.base, this.top].forEach(function (canvas) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
    });
    this.stage.style.height = height + 'px';
    this.redraw();
  };

  Widget.prototype.context = function (canvas) {
    var ctx = canvas.getContext('2d'), dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr * this.scale, 0, 0, dpr * this.scale, 0, 0);
    return ctx;
  };

  Widget.prototype.visibleLayers = function (page) {
    var own = this.editableLayer(page) || (this.role === 'teacher' ? 'teacher' : 'student');
    var order = ['student', 'teacher'];
    var self = this;
    return order.filter(function (name) {
      if (name === 'teacher' && self.role === 'student' && (!self.showTeacherLayer || !self.showTeacher)) return false;
      return true;
    }).map(function (name) { return {name: name, own: name === own}; });
  };

  Widget.prototype.redraw = function () {
    var self = this;
    if (this.raf) return;
    this.raf = requestAnimationFrame(function () {
      self.raf = null;
      self.drawBase();
      self.drawTop();
    });
  };

  Widget.prototype.drawBase = function () {
    var page = this.page();
    if (!page || !this.scale) return;
    var ctx = this.context(this.base);
    ctx.clearRect(0, 0, W, H);
    drawBackground(ctx, page);
    var self = this, drag = this.drag;
    this.visibleLayers(page).forEach(function (layer) {
      page.layers[layer.name].elements.forEach(function (element) {
        if (drag && drag.kind === 'move' && layer.own && drag.ids[element.id]) {
          drawElement(ctx, shifted(element, drag.dx, drag.dy), page);
        } else if (drag && drag.kind === 'handle' && layer.own && drag.preview && drag.preview.id === element.id) {
          drawElement(ctx, drag.preview, page);
        } else {
          drawElement(ctx, element, page);
        }
      });
    });
  };

  Widget.prototype.drawTop = function () {
    var page = this.page();
    if (!page || !this.scale) return;
    var ctx = this.context(this.top);
    ctx.clearRect(0, 0, W, H);
    var drag = this.drag;
    if (drag && drag.kind === 'draw' && drag.element) drawElement(ctx, drag.element, page);
    if (drag && drag.kind === 'shape' && drag.preview) drawElement(ctx, drag.preview, page);
    if (drag && drag.kind === 'erase') {
      ctx.strokeStyle = '#6b7686'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.arc(drag.at[0], drag.at[1], this.eraserSize, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
    }
    if (this.pending.length) {
      ctx.fillStyle = ACCENT;
      this.pending.forEach(function (pt) { ctx.beginPath(); ctx.arc(pt[0], pt[1], 4, 0, Math.PI * 2); ctx.fill(); });
      if (this.pending.length === 2) {
        ctx.strokeStyle = ACCENT; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(this.pending[0][0], this.pending[0][1]); ctx.lineTo(this.pending[1][0], this.pending[1][1]); ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (drag && drag.kind === 'band') {
      ctx.strokeStyle = ACCENT; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
      ctx.strokeRect(Math.min(drag.from[0], drag.to[0]), Math.min(drag.from[1], drag.to[1]),
        Math.abs(drag.to[0] - drag.from[0]), Math.abs(drag.to[1] - drag.from[1]));
      ctx.setLineDash([]);
    }
    if (this.selection.length && this.tool === 'select') {
      var elements = this.ownElements(page), self = this;
      ctx.strokeStyle = ACCENT; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
      var selected = elements.filter(function (e) { return self.selection.indexOf(e.id) >= 0; });
      selected.forEach(function (element) {
        var shown = drag && drag.kind === 'move' ? shifted(element, drag.dx, drag.dy) : element;
        var b = bbox(shown);
        ctx.strokeRect(b[0] - 3, b[1] - 3, b[2] - b[0] + 6, b[3] - b[1] + 6);
      });
      ctx.setLineDash([]);
      if (selected.length === 1 && selected[0].t === 'fn') {
        var fn = drag && drag.kind === 'handle' && drag.preview ? drag.preview : selected[0];
        ctx.fillStyle = '#fff'; ctx.strokeStyle = ACCENT; ctx.lineWidth = 2;
        fn.p.forEach(function (pt, i) {
          ctx.beginPath(); ctx.arc(pt[0], pt[1], 7, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
          if (i === 1) { ctx.fillStyle = ACCENT; ctx.beginPath(); ctx.arc(pt[0], pt[1], 3, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = '#fff'; }
        });
      }
    }
  };

  /* ---------- модель: команды, слой ---------- */

  Widget.prototype.ownElements = function (page) {
    var layer = this.editableLayer(page);
    return layer ? page.layers[layer].elements : [];
  };

  Widget.prototype.commit = function (page, after) {
    var layer = this.editableLayer(page);
    if (!layer) return;
    var before = page.layers[layer].elements;
    if (before === after) return;
    if (after.length > this.limits.elements) { toast(false, 'Слишком много элементов на странице'); return; }
    page.layers[layer].elements = after;
    page.undo.push({before: before, after: after});
    if (page.undo.length > MAX_UNDO) page.undo.shift();
    page.redo = [];
    this.touch(page);
    this.syncHistoryButtons(page);
  };

  Widget.prototype.syncHistoryButtons = function (page) {
    if (this.undoButton) this.undoButton.disabled = !page.undo.length;
    if (this.redoButton) this.redoButton.disabled = !page.redo.length;
    if (this.selectionGroup) this.selectionGroup.hidden = !this.selection.length;
  };

  Widget.prototype.undo = function () {
    var page = this.page(), layer = page && this.editableLayer(page);
    if (!layer || !page.undo.length) return;
    var step = page.undo.pop();
    page.layers[layer].elements = step.before;
    page.redo.push(step);
    this.selection = [];
    this.touch(page);
    this.syncHistoryButtons(page);
    this.redraw();
  };

  Widget.prototype.redo = function () {
    var page = this.page(), layer = page && this.editableLayer(page);
    if (!layer || !page.redo.length) return;
    var step = page.redo.pop();
    page.layers[layer].elements = step.after;
    page.undo.push(step);
    this.selection = [];
    this.touch(page);
    this.syncHistoryButtons(page);
    this.redraw();
  };

  Widget.prototype.clearPage = function () {
    var page = this.page();
    if (!page || !this.ownElements(page).length) return;
    this.selection = [];
    this.commit(page, []);
    this.redraw();
  };

  Widget.prototype.selectedElements = function () {
    var self = this;
    return this.ownElements(this.page()).filter(function (e) { return self.selection.indexOf(e.id) >= 0; });
  };

  Widget.prototype.deleteSelection = function () {
    var page = this.page(), self = this;
    if (!this.selection.length) return;
    this.commit(page, this.ownElements(page).filter(function (e) { return self.selection.indexOf(e.id) < 0; }));
    this.selection = [];
    this.syncHistoryButtons(page);
    this.redraw();
  };

  Widget.prototype.recolorSelection = function (color) {
    var page = this.page(), self = this;
    if (!this.selection.length || this.tool !== 'select') return;
    this.commit(page, this.ownElements(page).map(function (e) {
      if (self.selection.indexOf(e.id) < 0 || e.t === 'hl') return e;
      return Object.assign({}, e, {c: color});
    }));
    this.redraw();
  };

  Widget.prototype.groupSelection = function (make) {
    var page = this.page(), self = this;
    if (make && this.selection.length < 2) return;
    if (!this.selection.length) return;
    var gid = uid();
    this.commit(page, this.ownElements(page).map(function (e) {
      if (self.selection.indexOf(e.id) < 0) return e;
      var copy = Object.assign({}, e);
      if (make) copy.g = gid; else delete copy.g;
      return copy;
    }));
    this.redraw();
  };

  Widget.prototype.reorderSelection = function (toFront) {
    var page = this.page(), self = this;
    if (!this.selection.length) return;
    var elements = this.ownElements(page);
    var picked = elements.filter(function (e) { return self.selection.indexOf(e.id) >= 0; });
    var rest = elements.filter(function (e) { return self.selection.indexOf(e.id) < 0; });
    this.commit(page, toFront ? rest.concat(picked) : picked.concat(rest));
    this.redraw();
  };

  Widget.prototype.moveSelection = function (dx, dy) {
    var page = this.page(), self = this;
    if (!this.selection.length) return;
    this.commit(page, this.ownElements(page).map(function (e) {
      return self.selection.indexOf(e.id) >= 0 ? shifted(e, dx, dy) : e;
    }));
    this.redraw();
  };

  Widget.prototype.addElement = function (element) {
    var page = this.page();
    this.commit(page, this.ownElements(page).concat([element]));
    this.redraw();
  };

  Widget.prototype.insertFn = function (kind) {
    var page = this.page();
    if (!page || !this.editableLayer(page)) return;
    var cell = cellOf(page) || 25;
    var o = page.background === 'plane' ? planeOrigin(page) : [W / 2, H / 2];
    var element = {id: uid(), t: 'fn', k: kind, c: this.color, w: 2, p: [[o[0], o[1]], [o[0] + cell, o[1] - cell]]};
    this.addElement(element);
    this.tool = 'select';
    this.selection = [element.id];
    this.buildToolbar(true);
    this.drawTop();
  };

  /* Выделить элемент вместе с его группой */
  Widget.prototype.select = function (element, add) {
    var elements = this.ownElements(this.page());
    var ids = element.g ? elements.filter(function (e) { return e.g === element.g; }).map(function (e) { return e.id; }) : [element.id];
    if (add) {
      var self = this;
      ids.forEach(function (id) {
        var at = self.selection.indexOf(id);
        if (at >= 0) self.selection.splice(at, 1); else self.selection.push(id);
      });
    } else {
      this.selection = ids;
    }
    this.syncHistoryButtons(this.page());
  };

  /* ---------- указатель ---------- */

  Widget.prototype.point = function (e) {
    var rect = this.stage.getBoundingClientRect();
    return [(e.clientX - rect.left) / this.scale, (e.clientY - rect.top) / this.scale];
  };

  Widget.prototype.snapped = function (pt) {
    var page = this.page(), cell = cellOf(page);
    if (!this.snap || !cell) return pt;
    var o = page.background === 'plane' ? planeOrigin(page) : [0, 0];
    return [o[0] + Math.round((pt[0] - o[0]) / cell) * cell, o[1] + Math.round((pt[1] - o[1]) / cell) * cell];
  };

  Widget.prototype.onDown = function (e) {
    var page = this.page();
    if (!page || !this.editableLayer(page) || this.drag) return;
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    if (e.pointerType === 'pen') Widget.penSeen = true;
    if (e.pointerType === 'touch' && Widget.penSeen) return; /* ладонь при письме стилусом */
    e.preventDefault();
    this.stage.setPointerCapture(e.pointerId);
    var pt = this.point(e), tool = this.tool;
    if (tool === 'pen' || tool === 'hl') {
      var element = {id: uid(), t: tool === 'pen' ? 'path' : 'hl', c: tool === 'pen' ? this.color : this.hlColor,
        w: tool === 'pen' ? this.penWidth : this.hlWidth, p: [pt]};
      this.drag = {kind: 'draw', pointerId: e.pointerId, element: element};
    } else if (tool === 'eraser') {
      this.drag = {kind: 'erase', pointerId: e.pointerId, at: pt, before: this.ownElements(page), changed: false};
      this.eraseAt(pt);
    } else if (tool === 'select') {
      this.startSelect(e, pt);
    } else if (tool === 'dot') {
      var snappedPt = roundPoint(this.snapped(pt));
      this.addElement({id: uid(), t: 'dot', c: this.color, w: Math.max(3, this.penWidth), p: [snappedPt], l: page.background === 'plane' && this.snap});
    } else if (tool === 'tri' || tool === 'para') {
      this.pending.push(roundPoint(this.snapped(pt)));
      if (this.pending.length === 3) {
        this.addElement({id: uid(), t: tool, c: this.color, w: this.penWidth, p: this.pending});
        this.pending = [];
      }
      this.drawTop();
    } else {
      this.drag = {kind: 'shape', pointerId: e.pointerId, from: roundPoint(this.snapped(pt)), preview: null};
    }
    this.drawTop();
  };

  Widget.prototype.startSelect = function (e, pt) {
    var page = this.page(), elements = this.ownElements(page);
    var selected = this.selectedElements();
    if (selected.length === 1 && selected[0].t === 'fn') {
      var fn = selected[0];
      for (var i = 1; i >= 0; i--) {
        if (dist(fn.p[i], pt) <= 12) {
          this.drag = {kind: 'handle', pointerId: e.pointerId, element: fn, index: i, preview: null};
          return;
        }
      }
    }
    var hit = null;
    for (var j = elements.length - 1; j >= 0; j--) {
      if (hits(elements[j], pt, HIT_TOL)) { hit = elements[j]; break; }
    }
    if (hit) {
      if (this.selection.indexOf(hit.id) < 0 || e.shiftKey) this.select(hit, e.shiftKey);
      var ids = {};
      this.selection.forEach(function (id) { ids[id] = true; });
      this.drag = {kind: 'move', pointerId: e.pointerId, from: pt, dx: 0, dy: 0, ids: ids};
    } else {
      if (!e.shiftKey) this.selection = [];
      this.drag = {kind: 'band', pointerId: e.pointerId, from: pt, to: pt, add: e.shiftKey};
    }
    this.syncHistoryButtons(page);
    this.redraw();
  };

  Widget.prototype.onMove = function (e) {
    var drag = this.drag;
    if (!drag || drag.pointerId !== e.pointerId) return;
    e.preventDefault();
    var self = this;
    var events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    if (!events.length) events = [e];
    var pt = this.point(events[events.length - 1]);
    switch (drag.kind) {
      case 'draw':
        events.forEach(function (ev) { drag.element.p.push(self.point(ev)); });
        this.drawTop();
        return;
      case 'erase':
        events.forEach(function (ev) { self.eraseAt(self.point(ev)); });
        drag.at = pt;
        this.drawTop();
        return;
      case 'move':
        drag.dx = pt[0] - drag.from[0];
        drag.dy = pt[1] - drag.from[1];
        if (this.snap) {
          var first = this.selectedElements()[0];
          if (first) {
            var anchor = this.snapped([first.p[0][0] + drag.dx, first.p[0][1] + drag.dy]);
            drag.dx = anchor[0] - first.p[0][0]; drag.dy = anchor[1] - first.p[0][1];
          }
        }
        this.redraw();
        return;
      case 'band':
        drag.to = pt;
        this.drawTop();
        return;
      case 'handle': {
        var target = roundPoint(this.snapped(pt)), fn = drag.element, points;
        if (drag.index === 0) {
          var dx = target[0] - fn.p[0][0], dy = target[1] - fn.p[0][1];
          points = [target, [fn.p[1][0] + dx, fn.p[1][1] + dy]];
        } else {
          points = [fn.p[0], target];
        }
        drag.preview = Object.assign({}, fn, {p: points});
        this.redraw();
        return;
      }
      case 'shape':
        drag.preview = this.shapeFrom(drag.from, roundPoint(this.snapped(pt)), e.shiftKey);
        this.drawTop();
        return;
    }
  };

  Widget.prototype.shapeFrom = function (from, to, shift) {
    var tool = this.tool, base = {id: uid(), c: this.color, w: this.penWidth};
    if (tool === 'line') {
      if (shift) {
        var dx = to[0] - from[0], dy = to[1] - from[1], angle = Math.atan2(dy, dx);
        var snapAngle = Math.round(angle / (Math.PI / 4)) * (Math.PI / 4), len = Math.hypot(dx, dy);
        to = roundPoint([from[0] + len * Math.cos(snapAngle), from[1] + len * Math.sin(snapAngle)]);
      }
      return Object.assign(base, {t: 'line', p: [from, to]});
    }
    if (tool === 'circle') return Object.assign(base, {t: 'circle', p: [from, to]});
    if (tool === 'square' || (tool === 'rect' && shift)) {
      var side = Math.max(Math.abs(to[0] - from[0]), Math.abs(to[1] - from[1]));
      to = [from[0] + side * (to[0] < from[0] ? -1 : 1), from[1] + side * (to[1] < from[1] ? -1 : 1)];
    }
    return Object.assign(base, {t: 'rect', p: [from, to]});
  };

  Widget.prototype.onUp = function (e, cancelled) {
    var drag = this.drag;
    if (!drag || drag.pointerId !== e.pointerId) return;
    this.drag = null;
    var page = this.page(), self = this;
    try { this.stage.releasePointerCapture(e.pointerId); } catch (err) {}
    if (cancelled) { this.redraw(); return; }
    switch (drag.kind) {
      case 'draw': {
        var points = simplify(drag.element.p, 0.6).map(roundPoint);
        drag.element.p = points;
        this.addElement(drag.element);
        break;
      }
      case 'erase':
        if (drag.changed) {
          var layer = this.editableLayer(page), after = page.layers[layer].elements;
          page.layers[layer].elements = drag.before;
          this.commit(page, after);
        }
        this.redraw();
        break;
      case 'move':
        if (drag.dx || drag.dy) this.moveSelection(drag.dx, drag.dy); else this.redraw();
        break;
      case 'band': {
        var box = [Math.min(drag.from[0], drag.to[0]), Math.min(drag.from[1], drag.to[1]),
                   Math.max(drag.from[0], drag.to[0]), Math.max(drag.from[1], drag.to[1])];
        if (box[2] - box[0] > 4 || box[3] - box[1] > 4) {
          var picked = this.ownElements(page).filter(function (el) { return insideBox(el, box); });
          picked.forEach(function (el) { self.select(el, true); });
          if (!drag.add) {
            var ids = {}; picked.forEach(function (el) { ids[el.id] = true; });
            this.selection = this.ownElements(page).filter(function (el) {
              return ids[el.id] || (el.g && picked.some(function (p) { return p.g === el.g; }));
            }).map(function (el) { return el.id; });
          }
        }
        this.syncHistoryButtons(page);
        this.redraw();
        break;
      }
      case 'handle':
        if (drag.preview) {
          var preview = drag.preview;
          this.commit(page, this.ownElements(page).map(function (el) { return el.id === preview.id ? preview : el; }));
        }
        this.redraw();
        break;
      case 'shape':
        if (drag.preview && dist(drag.preview.p[0], drag.preview.p[1]) >= 3) this.addElement(drag.preview);
        else this.drawTop();
        break;
    }
  };

  Widget.prototype.eraseAt = function (pt) {
    var page = this.page(), layer = this.editableLayer(page), drag = this.drag;
    if (!layer) return;
    var r = this.eraserSize, elements = page.layers[layer].elements, next = [], changed = false;
    elements.forEach(function (element) {
      if (element.t !== 'path' && element.t !== 'hl') { next.push(element); return; }
      var box = bbox(element);
      if (pt[0] < box[0] - r || pt[0] > box[2] + r || pt[1] < box[1] - r || pt[1] > box[3] + r) { next.push(element); return; }
      var pieces = eraseFromPath(element, pt, r);
      if (pieces === null) { next.push(element); return; }
      changed = true;
      pieces.forEach(function (piece) { next.push(piece); });
    });
    if (changed) {
      page.layers[layer].elements = next;
      if (drag) drag.changed = true;
      this.redraw();
    }
  };

  /* ---------- клавиатура ---------- */

  document.addEventListener('keydown', function (e) {
    var widget = Widget.active;
    if (!widget || !widget.built) return;
    var target = e.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable || target.tagName === 'MATH-FIELD')) return;
    var page = widget.page();
    if (!page || !widget.editableLayer(page)) return;
    var key = e.key, mod = e.ctrlKey || e.metaKey;
    if (mod && (key === 'z' || key === 'Z' || key === 'я' || key === 'Я')) { e.preventDefault(); if (e.shiftKey) widget.redo(); else widget.undo(); return; }
    if (mod && (key === 'y' || key === 'Y')) { e.preventDefault(); widget.redo(); return; }
    if (mod && (key === 'g' || key === 'G' || key === 'п' || key === 'П')) { e.preventDefault(); widget.groupSelection(!e.shiftKey); return; }
    if (mod) return;
    if (key === 'Escape') { widget.pending = []; widget.selection = []; widget.syncHistoryButtons(page); widget.redraw(); return; }
    if (key === 'Delete' || key === 'Backspace') { if (widget.selection.length) { e.preventDefault(); widget.deleteSelection(); } return; }
    if (key === ']') { widget.reorderSelection(true); return; }
    if (key === '[') { widget.reorderSelection(false); return; }
    if (key.indexOf('Arrow') === 0 && widget.selection.length) {
      e.preventDefault();
      var step = e.shiftKey ? 10 : 1;
      widget.moveSelection(key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0,
                           key === 'ArrowUp' ? -step : key === 'ArrowDown' ? step : 0);
      return;
    }
    var tools = {v: 'select', h: 'select', p: 'pen', P: 'hl', e: 'eraser', o: 'rect', s: 'circle', l: 'line',
                 м: 'select', р: 'select', з: 'pen', З: 'hl', у: 'eraser', щ: 'rect', ы: 'circle', д: 'line'};
    var name = tools[e.shiftKey && (key === 'P' || key === 'З') ? key : key.toLowerCase()];
    if (key === 'P' || key === 'З') name = 'hl';
    if (name) { e.preventDefault(); widget.setTool(name); }
  });

  /* ---------- сохранение ---------- */

  Widget.prototype.touch = function (page) {
    var self = this;
    page.rev++;
    page.dirty = true;
    this.updateNonEmpty();
    if (!page.firstDirtyAt) page.firstDirtyAt = Date.now();
    clearTimeout(page.timer);
    var wait = Date.now() - page.firstDirtyAt >= MAX_WAIT ? 0 : DEBOUNCE;
    page.timer = setTimeout(function () { self.save(page); }, wait);
  };

  Widget.prototype.updateNonEmpty = function () {
    var any = this.pages.some(function (p) { return p.layers.student.elements.length || p.layers.teacher.elements.length; });
    this.root.dataset.nonempty = any ? '1' : '';
  };

  Widget.prototype.body = function (page, layer) {
    return JSON.stringify({
      layer: layer, elements: page.layers[layer].elements, version: page.layers[layer].version,
      background: page.background, background_options: page.bgOptions,
    });
  };

  Widget.prototype.flush = function (page) {
    if (page && page.dirty && !page.saving) { clearTimeout(page.timer); return this.save(page); }
    return Promise.resolve(true);
  };

  Widget.prototype.flushAll = function () {
    var self = this;
    return Promise.all(this.pages.map(function (page) { return self.flush(page); }));
  };

  Widget.prototype.save = function (page) {
    var self = this, layer = this.editableLayer(page);
    clearTimeout(page.timer);
    if (!layer || !page.dirty) return Promise.resolve(true);
    if (page.saving) { page.pendingSave = true; return Promise.resolve(false); }
    page.saving = true;
    var rev = page.rev, body = this.body(page, layer);
    var enqueue = window.EgorAutosave && EgorAutosave.enqueue || function (_, operation) { return operation(); };
    return enqueue(this, function () {
      return fetch(self.url + page.number + '/', {
        method: 'POST', credentials: 'same-origin', body: body,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
      }).then(function (r) { return r.json().then(function (data) { return {status: r.status, data: data}; }); });
    }).then(function (result) {
      var data = result.data || {};
      page.saving = false;
      if (data.ok) {
        page.layers[layer].version = data.version;
        page.retry = 0;
        self.dropBackup(page, layer);
        if (page.rev === rev) { page.dirty = false; page.firstDirtyAt = 0; }
        toast(true, data.message || 'Сохранено ✓');
      } else if (result.status === 409 && data.elements) {
        page.layers[layer].elements = data.elements;
        page.layers[layer].version = data.version;
        page.undo = []; page.redo = [];
        page.dirty = false; page.firstDirtyAt = 0;
        self.selection = [];
        self.dropBackup(page, layer);
        toast(false, data.message || 'Страница изменена в другом окне');
        self.redraw();
        self.syncHistoryButtons(page);
      } else if (result.status === 403 || result.status === 503) {
        page.dirty = false; page.firstDirtyAt = 0;
        page.locked = page.locked || result.status === 403;
        toast(false, data.message || 'Изменения не сохранены');
        self.refresh();
      } else {
        page.dirty = false;
        toast(false, data.message || 'Ошибка сохранения');
      }
      if (page.pendingSave || (page.dirty && page.rev !== rev)) { page.pendingSave = false; self.touch(page); }
      return !!data.ok;
    }).catch(function () {
      page.saving = false;
      self.storeBackup(page, layer);
      var delay = RETRY[Math.min(page.retry, RETRY.length - 1)];
      page.retry++;
      toast(false, 'Нет связи — холст не сохранён, повторю через ' + Math.round(delay / 1000) + ' с');
      page.timer = setTimeout(function () { self.save(page); }, delay);
      return false;
    });
  };

  Widget.prototype.backupKey = function (page, layer) { return 'canvas-backup:' + this.url + page.number + ':' + layer; };
  Widget.prototype.storeBackup = function (page, layer) {
    try {
      localStorage.setItem(this.backupKey(page, layer), JSON.stringify({
        elements: page.layers[layer].elements, version: page.layers[layer].version,
        background: page.background, background_options: page.bgOptions, ts: Date.now(),
      }));
    } catch (e) {}
  };
  Widget.prototype.dropBackup = function (page, layer) {
    try { localStorage.removeItem(this.backupKey(page, layer)); } catch (e) {}
  };
  /* Черновик, не дошедший до сервера (закрыли вкладку без сети): если сервер
     с тех пор ничего нового не получил, отправляем его снова */
  Widget.prototype.restoreBackup = function (page) {
    var layer = this.editableLayer(page);
    if (!layer) return;
    var raw = null;
    try { raw = localStorage.getItem(this.backupKey(page, layer)); } catch (e) {}
    if (!raw) return;
    var backup = null;
    try { backup = JSON.parse(raw); } catch (e) {}
    if (!backup || backup.version !== page.layers[layer].version) { this.dropBackup(page, layer); return; }
    page.layers[layer].elements = backup.elements || [];
    page.background = backup.background || page.background;
    page.bgOptions = backup.background_options || page.bgOptions;
    this.touch(page);
  };

  /* Уход со страницы: маленькое тело уходит keepalive-запросом (лимит браузера
     64 КБ), большое остаётся черновиком в localStorage до следующего открытия */
  window.addEventListener('pagehide', function () {
    Widget.all.forEach(function (widget) {
      widget.pages.forEach(function (page) {
        var layer = widget.editableLayer(page);
        if (!layer || !page.dirty) return;
        clearTimeout(page.timer);
        var body = widget.body(page, layer);
        widget.storeBackup(page, layer);
        if (body.length < KEEPALIVE_LIMIT && typeof fetch === 'function') {
          fetch(widget.url + page.number + '/', {
            method: 'POST', credentials: 'same-origin', body: body, keepalive: true,
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
          }).then(function (r) { if (r.ok) widget.dropBackup(page, layer); }).catch(function () {});
        }
      });
    });
  });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) Widget.all.forEach(function (widget) { widget.flushAll(); });
  });

  /* «Отправить на проверку»: сначала дописываем холст, потом обычный submit */
  document.addEventListener('click', function (e) {
    var button = e.target.closest && e.target.closest('#submit-assignment');
    if (!button || button.dataset.canvasFlushed) return;
    var dirty = Widget.all.some(function (w) { return w.pages.some(function (p) { return p.dirty; }); });
    if (!dirty) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    Promise.all(Widget.all.map(function (w) { return w.flushAll(); })).then(function () {
      button.dataset.canvasFlushed = '1';
      button.click();
      delete button.dataset.canvasFlushed;
    });
  }, true);

  /* ---------- инициализация ---------- */

  Widget.all = [];
  Widget.penSeen = false;
  Widget.active = null;

  function init(root) {
    if (root.canvasWidget || !root.dataset.url) return;
    Widget.all.push(new Widget(root));
  }
  function initAll(scope) {
    (scope || document).querySelectorAll('[data-canvas]').forEach(init);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('toggle-canvas');
    if (toggle) {
      try { toggle.checked = localStorage.getItem(SHOW_KEY) === '1'; } catch (e) {}
      toggle.addEventListener('change', function () {
        try { localStorage.setItem(SHOW_KEY, toggle.checked ? '1' : ''); } catch (e) {}
        Widget.all.forEach(function (w) { if (w.role !== 'student') w.applyTeacherToggle(); });
      });
    }
    initAll();
    /* Живой обзор подменяет фрагменты с ответами — холсты в них поднимаем заново */
    if (window.MutationObserver) {
      new MutationObserver(function (records) {
        records.forEach(function (record) {
          record.addedNodes.forEach(function (node) {
            if (node.nodeType !== 1) return;
            if (node.matches && node.matches('[data-canvas]')) init(node);
            else if (node.querySelectorAll) initAll(node);
          });
        });
        Widget.all = Widget.all.filter(function (w) { return document.body.contains(w.root); });
      }).observe(document.body, {childList: true, subtree: true});
    }
  });

  window.EgorCanvas = {Widget: Widget, init: initAll};
})();
