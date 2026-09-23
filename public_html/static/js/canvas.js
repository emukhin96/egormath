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

  var W = 1000, H = 1000;
  var COLORS = ['#111827', '#1d4ed8', '#dc2626', '#16a34a', '#ea580c', '#7c3aed'];
  var HL_COLORS = ['#facc15', '#4ade80', '#f472b6', '#38bdf8', '#fb923c', '#c084fc'];
  var COLOR_NAMES = {'#111827': 'чёрный', '#1d4ed8': 'синий', '#dc2626': 'красный', '#16a34a': 'зелёный',
    '#ea580c': 'оранжевый', '#7c3aed': 'фиолетовый', '#facc15': 'жёлтый', '#4ade80': 'салатовый',
    '#f472b6': 'розовый', '#38bdf8': 'голубой', '#fb923c': 'оранжевый', '#c084fc': 'сиреневый'};
  var SIZE_NAMES = ['тонкая', 'средняя', 'толстая'], ERASER_NAMES = ['малый', 'средний', 'большой'];
  var PEN_WIDTHS = [2, 4, 7], HL_WIDTHS = [12, 20, 30], ERASER_SIZES = [10, 25, 50];
  var HL_ALPHA = 0.35, HIT_TOL = 8, MAX_UNDO = 100;
  var DEBOUNCE = 1000, MAX_WAIT = 5000, RETRY = [3000, 10000, 30000], KEEPALIVE_LIMIT = 60000;
  var SHOW_KEY = 'canvas-show', HIDE_TEACHER_KEY = 'canvas-hide-teacher';
  var POLL = 10000;               /* опрос чужого слоя, пока доска открыта и вкладка видна */
  var GRID_COLOR = '#d4d4d8', ACCENT = '#1765b5';
  var CELLS = {grid: 25, grid_large: 50};
  var FN = {
    parabola: {label: 'x²', title: 'Парабола y = x²', f: function (x) { return x * x; }},
    abs: {label: '|x|', title: 'Модуль y = |x|', f: function (x) { return Math.abs(x); }},
    sqrt: {label: '√x', title: 'Корень y = √x', f: function (x) { return x < 0 ? NaN : Math.sqrt(x); }},
    hyperbola: {label: '1/x', title: 'Гипербола y = 1/x', f: function (x) { return x === 0 ? NaN : 1 / x; }},
  };
  var SHAPE_TOOLS = {
    line: {label: '—', title: 'Отрезок: протяните от точки до точки, с Shift — горизонтально, вертикально или под 45° (L)'},
    dot: {label: '•', title: 'Точка: один клик; на координатной плоскости с привязкой к сетке подписываются координаты'},
    circle: {label: '○', title: 'Окружность: протяните от центра до точки на окружности (S)'},
    rect: {label: '▭', title: 'Прямоугольник: протяните по диагонали, с Shift — квадрат (O)'},
    square: {label: '□', title: 'Квадрат: протяните по диагонали'},
    tri: {label: '△', title: 'Треугольник: три клика по вершинам, Esc — отменить'},
    para: {label: '▱', title: 'Параллелограмм: три клика по вершинам, четвёртая достроится, Esc — отменить'},
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
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    if (onclick) b.addEventListener('click', onclick);
    return b;
  }
  var ICONS = {
    pen: '<path d="m4 16-1 5 5-1L20 8l-4-4Z M14 6l4 4"/>',
    hl: '<path d="m5 14 5 5 10-10-5-5Z M5 14l-2 5 2 2 5-2 M3 22h11"/>',
    eraser: '<path d="m3 14 10-10a2 2 0 0 1 3 0l5 5a2 2 0 0 1 0 3l-9 9H8Z M8 9l8 8 M12 21h10"/>',
    select: '<path d="m5 3 14 10-7 1-3 7Z"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    undo: '<path d="M9 4 3 10l6 6 M3 10h11a7 7 0 0 1 0 14" transform="translate(0 -2)"/>',
    redo: '<path d="m15 4 6 6-6 6 M21 10H10a7 7 0 0 0 0 14" transform="translate(0 -2)"/>',
    trash: '<path d="M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7"/>',
    clear: '<path d="m13 9 7-7 M3 15l6-6 6 6-6 6Z M5 17l4-4 M7 19l4-4 M15 21h7"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    group: '<rect x="3" y="3" width="12" height="12" rx="1"/><rect x="9" y="9" width="12" height="12" rx="1"/>',
    ungroup: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><path d="m14 3 7 7 M21 3l-7 7"/>',
    front: '<path d="m8 8 4-5 4 5 M12 3v12 M4 13v8h16v-8"/>',
    back: '<path d="m8 13 4 5 4-5 M12 3v15 M4 13v8h16v-8"/>',
  };
  function addIcon(node, name) {
    node.classList.add('canvas-icon');
    node.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>';
    return node;
  }
  function iconButton(name, title, action) {
    return addIcon(button(name === 'trash' ? 'icon-btn' : 'btn btn-small btn-secondary', '', title, action), name);
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
      // Асимптота может оказаться между отсчётами: ветви не соединяем.
      if (element.k === 'hyperbola' && current.length
          && (current[current.length - 1][0] - o[0]) * (px - o[0]) < 0) {
        if (current.length > 1) lines.push(current);
        current = [];
      }
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

  /* ---------- рисунок задачи (t: 'img') ----------
     p = [левый верхний, правый верхний, левый нижний] угол; четвёртый угол
     выводится. Три точки задают аффинное преобразование: перенос, масштаб
     по двум осям, поворот и наклон — рисуется одним ctx.transform + drawImage. */
  var imageCache = {};
  function imageOf(url) {
    var entry = imageCache[url];
    if (entry) return entry;
    entry = imageCache[url] = {img: new Image(), ready: false, failed: false, waiters: []};
    var settle = function () {
      var waiters = entry.waiters; entry.waiters = [];
      waiters.forEach(function (fn) { fn(entry); });
    };
    entry.img.onload = function () { entry.ready = true; settle(); };
    entry.img.onerror = function () { entry.failed = true; settle(); };
    entry.img.src = url;
    return entry;
  }
  /* Ожидание конкретной картинки: fn(entry) один раз, когда она загрузилась
     или не смогла; уже загруженная — сразу. Подписка не дублируется. */
  function whenImageSettles(url, fn) {
    var entry = imageOf(url);
    if (entry.ready || entry.failed) { fn(entry); return; }
    if (entry.waiters.indexOf(fn) < 0) entry.waiters.push(fn);
  }
  /* Ещё не загруженные картинки среди элементов */
  function pendingImages(elements) {
    var urls = [];
    elements.forEach(function (element) {
      if (element.t !== 'img' || !element.u) return;
      var entry = imageOf(element.u);
      if (!entry.ready && !entry.failed && urls.indexOf(element.u) < 0) urls.push(element.u);
    });
    return urls;
  }

  function imgCorners(element) {
    var p = element.p;
    return [p[0], p[1], [p[1][0] + p[2][0] - p[0][0], p[1][1] + p[2][1] - p[0][1]], p[2]];
  }
  function imgCenter(element) {
    var c = imgCorners(element);
    return [(c[0][0] + c[2][0]) / 2, (c[0][1] + c[2][1]) / 2];
  }
  function insideParallelogram(element, pt) {
    var p = element.p, u = [p[1][0] - p[0][0], p[1][1] - p[0][1]], v = [p[2][0] - p[0][0], p[2][1] - p[0][1]];
    var det = u[0] * v[1] - u[1] * v[0];
    if (Math.abs(det) < 1e-6) return false;
    var dx = pt[0] - p[0][0], dy = pt[1] - p[0][1];
    var a = (dx * v[1] - dy * v[0]) / det, b = (u[0] * dy - u[1] * dx) / det;
    return a >= 0 && a <= 1 && b >= 0 && b <= 1;
  }
  /* Ручки: углы (масштаб), середины сторон (наклон), кружок над верхом (поворот) */
  var IMG_ROTATE_GAP = 40;
  function imgHandles(element) {
    var c = imgCorners(element), mid = function (a, b) { return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; };
    var top = mid(c[0], c[1]), center = imgCenter(element);
    var len = dist(top, center) || 1, n = [(top[0] - center[0]) / len, (top[1] - center[1]) / len];
    return [
      {kind: 'corner', index: 0, at: c[0]}, {kind: 'corner', index: 1, at: c[1]},
      {kind: 'corner', index: 2, at: c[2]}, {kind: 'corner', index: 3, at: c[3]},
      {kind: 'side', index: 0, at: top}, {kind: 'side', index: 1, at: mid(c[1], c[2])},
      {kind: 'side', index: 2, at: mid(c[2], c[3])}, {kind: 'side', index: 3, at: mid(c[3], c[0])},
      {kind: 'rotate', index: 0, at: [top[0] + n[0] * IMG_ROTATE_GAP, top[1] + n[1] * IMG_ROTATE_GAP]},
    ];
  }
  function imgFromCorners(element, tl, tr, bl) {
    return Object.assign({}, element, {p: [roundPoint(tl), roundPoint(tr), roundPoint(bl)]});
  }
  /* Новое положение рисунка после перетаскивания ручки: element — исходный,
     start — где ручку взяли, pt — где курсор, shift — модификатор */
  function imgTransform(element, handle, start, pt, shift) {
    var p = element.p, tl = p[0], tr = p[1], bl = p[2];
    var u = [tr[0] - tl[0], tr[1] - tl[1]], v = [bl[0] - tl[0], bl[1] - tl[1]];
    if (handle.kind === 'corner') {
      var a = handle.index === 1 || handle.index === 2 ? 1 : 0, b = handle.index >= 2 ? 1 : 0;
      var anchor = [tl[0] + (1 - a) * u[0] + (1 - b) * v[0], tl[1] + (1 - a) * u[1] + (1 - b) * v[1]];
      var su = 2 * a - 1, sv = 2 * b - 1, d = [pt[0] - anchor[0], pt[1] - anchor[1]];
      var det = u[0] * v[1] - u[1] * v[0];
      if (Math.abs(det) < 1e-6) return element;
      var ku = (d[0] * v[1] - d[1] * v[0]) / det * su, kv = (u[0] * d[1] - u[1] * d[0]) / det * sv;
      if (shift) { var k = (ku + kv) / 2; ku = kv = k; }
      ku = Math.max(ku, 0.05); kv = Math.max(kv, 0.05);
      var nu = [u[0] * ku, u[1] * ku], nv = [v[0] * kv, v[1] * kv];
      var ntl = [anchor[0] - (1 - a) * nu[0] - (1 - b) * nv[0], anchor[1] - (1 - a) * nu[1] - (1 - b) * nv[1]];
      return imgFromCorners(element, ntl, [ntl[0] + nu[0], ntl[1] + nu[1]], [ntl[0] + nv[0], ntl[1] + nv[1]]);
    }
    if (handle.kind === 'rotate') {
      var c = imgCenter(element);
      var angle = Math.atan2(pt[1] - c[1], pt[0] - c[0]) - Math.atan2(start[1] - c[1], start[0] - c[0]);
      if (shift) {
        var current = Math.atan2(u[1], u[0]), step = Math.PI / 12;
        angle = Math.round((current + angle) / step) * step - current;
      }
      var cos = Math.cos(angle), sin = Math.sin(angle);
      var rot = function (q) { var x = q[0] - c[0], y = q[1] - c[1]; return [c[0] + x * cos - y * sin, c[1] + x * sin + y * cos]; };
      return imgFromCorners(element, rot(tl), rot(tr), rot(bl));
    }
    /* side: верх/низ сдвигаются вдоль u, лево/право — вдоль v */
    var axis = handle.index % 2 === 0 ? u : v, len = Math.hypot(axis[0], axis[1]) || 1;
    var hat = [axis[0] / len, axis[1] / len];
    var t = (pt[0] - start[0]) * hat[0] + (pt[1] - start[1]) * hat[1];
    var sh = [hat[0] * t, hat[1] * t];
    switch (handle.index) {
      case 0: return imgFromCorners(element, [tl[0] + sh[0], tl[1] + sh[1]], [tr[0] + sh[0], tr[1] + sh[1]], bl);
      case 2: return imgFromCorners(element, tl, tr, [bl[0] + sh[0], bl[1] + sh[1]]);
      case 1: return imgFromCorners(element, tl, [tr[0] + sh[0], tr[1] + sh[1]], bl);
      default: return imgFromCorners(element, [tl[0] + sh[0], tl[1] + sh[1]], tr, [bl[0] + sh[0], bl[1] + sh[1]]);
    }
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
      case 'img': { var ic = imgCorners(element); return [ic.concat([ic[0]])]; }
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
    if (element.t === 'img' && insideParallelogram(element, pt)) return true;
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

  // Старые страницы 1000×750 размещаем в квадрате без изменения рисунков
  // и их положения относительно осей. Новые сразу имеют размер 1000×1000.
  function offsetOf(page) {
    if (!page || page.bgOptions.square) return 0;
    if (page.background === 'plane') {
      var cell = page.bgOptions.cell || 25;
      return page.bgOptions.origin === 'bottom_left' ? 250 : H / 2 - Math.round(375 / cell) * cell;
    }
    return 125;
  }

  function planeOrigin(page) {
    var cell = page.bgOptions.cell || 25;
    var height = page.bgOptions.square ? H : 750;
    if (page.bgOptions.origin === 'bottom_left') return [cell * 2, height - cell * 2];
    return [W / 2, Math.round(height / 2 / cell) * cell];
  }
  function cellOf(page) {
    if (page.background === 'plane') return page.bgOptions.cell || 25;
    return CELLS[page.background] || 0;
  }

  function drawBackground(ctx, page) {
    ctx.fillStyle = '#fff';
    var top = -offsetOf(page), bottom = top + H;
    ctx.fillRect(0, top, W, H);
    var cell = cellOf(page);
    if (!cell) return;
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var x = 0; x <= W; x += cell) { ctx.moveTo(x, top); ctx.lineTo(x, bottom); }
    for (var y = Math.floor(top / cell) * cell; y <= bottom; y += cell) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
    if (page.background !== 'plane') return;
    var o = planeOrigin(page);
    ctx.strokeStyle = '#111';
    ctx.fillStyle = '#111';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(0, o[1]); ctx.lineTo(W, o[1]);
    ctx.moveTo(o[0], bottom); ctx.lineTo(o[0], top);
    /* единичные отметки, как в образцах xoy */
    ctx.moveTo(o[0] + cell, o[1] - 5); ctx.lineTo(o[0] + cell, o[1] + 5);
    ctx.moveTo(o[0] - 5, o[1] - cell); ctx.lineTo(o[0] + 5, o[1] - cell);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(W, o[1]); ctx.lineTo(W - 14, o[1] - 5); ctx.lineTo(W - 14, o[1] + 5); ctx.closePath();
    ctx.moveTo(o[0], top); ctx.lineTo(o[0] - 5, top + 14); ctx.lineTo(o[0] + 5, top + 14); ctx.closePath();
    ctx.fill();
    ctx.font = 'italic 20px "Times New Roman", serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('x', W - 12, o[1] + 8);
    ctx.textAlign = 'left';
    ctx.fillText('y', o[0] + 10, top + 2);
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
      case 'img': {
        var entry = element.u ? imageOf(element.u) : null;
        var ic = imgCorners(element);
        if (entry && entry.ready) {
          var iw = entry.img.naturalWidth || 1, ih = entry.img.naturalHeight || 1;
          ctx.transform((p[1][0] - p[0][0]) / iw, (p[1][1] - p[0][1]) / iw, (p[2][0] - p[0][0]) / ih, (p[2][1] - p[0][1]) / ih, p[0][0], p[0][1]);
          ctx.drawImage(entry.img, 0, 0, iw, ih);
        } else {
          /* Пока картинка грузится (или не загрузилась) — серый параллелограмм */
          ctx.fillStyle = entry && entry.failed ? '#fecaca' : '#e5e7eb';
          ctx.beginPath(); ctx.moveTo(ic[0][0], ic[0][1]);
          for (var q = 1; q < 4; q++) ctx.lineTo(ic[q][0], ic[q][1]);
          ctx.closePath(); ctx.fill();
        }
        break;
      }
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
    try { this.showTeacher = localStorage.getItem(HIDE_TEACHER_KEY) !== '1'; } catch (e) {}
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
    this.launcher = root.id && document.querySelector('[data-canvas-open="' + root.id + '"]');
    if (!this.launcher) {
      this.launcher = button('btn btn-small btn-secondary canvas-launch', 'Доска для записей', 'Открыть доску для записей');
      root.parentNode.insertBefore(this.launcher, root);
    }
    var self = this;
    this.launcher.addEventListener('click', function () { if (self.root.hidden) self.show(true); else self.close(); });
    var count = parseInt(root.dataset.pages || '0', 10) || 0;
    if (this.role === 'student') {
      if (count) this.show();
      else this.renderLauncher();
    } else {
      this.applyTeacherToggle();
    }
  }

  Widget.prototype.renderLauncher = function () {
    this.root.hidden = true;
    this.launcher.hidden = false;
    this.launcher.setAttribute('aria-expanded', 'false');
  };

  Widget.prototype.close = function () {
    if (this.drag) this.onUp({pointerId: this.drag.pointerId}, true);
    this.pending = [];
    this.flushAll();
    if (Widget.active === this) Widget.active = null;
    this.renderLauncher();
  };

  /* Тумблер «Показать доски для записей» включён по умолчанию: выключает только
     явное '0' в localStorage. Пустая доска (data-pages="0") не запрашивается —
     показывается кнопка, как у ученика; выключенная — просто скрыта. */
  Widget.showEnabled = function () {
    try { return localStorage.getItem(SHOW_KEY) !== '0'; } catch (e) { return true; }
  };

  Widget.prototype.applyTeacherToggle = function () {
    var count = parseInt(this.root.dataset.pages || '0', 10) || 0;
    /* data-always — виджет в диалоге дашборда: там нет тумблера, доска нужна всегда */
    if (this.root.dataset.always) { this.show(); return; }   /* в диалоге доска нужна даже пустая */
    if (Widget.showEnabled()) {
      if (count || this.loaded) this.show(); else this.renderLauncher();
      return;
    }
    if (this.drag) this.onUp({pointerId: this.drag.pointerId}, true);
    this.flushAll();
    if (this.resizeObserver) this.resizeObserver.disconnect();
    this.built = false;
    this.root.hidden = true;
    this.root.innerHTML = '';
    this.launcher.hidden = true;
  };

  Widget.prototype.show = function (createFirst) {
    var self = this;
    this.root.hidden = false;
    this.launcher.hidden = false;
    this.launcher.setAttribute('aria-expanded', 'true');
    if (this.loaded) {
      if (!this.pages.length && createFirst && this.layer) this.addPage();
      this.build(); return;
    }
    fetch(this.url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.json().then(function (data) { return {status: r.status, data: data, etag: r.headers.get('ETag')}; }); })
      .then(function (result) {
        if (!result.data || !result.data.ok) throw new Error(result.data && result.data.message || 'Не удалось загрузить доску для записей');
        self.etag = result.etag;
        self.applyData(result.data);
        self.loaded = true;
        if (!self.pages.length && createFirst && self.layer) self.addPage();
        self.build();
      })
      .catch(function (error) { toast(false, error.message || 'Не удалось загрузить доску для записей'); });
  };

  /* Забрать чужой слой (и новые страницы) с сервера, не трогая свой: свой
     слой защищён версией и 409, чужой просто подменяется. Вызывается живым
     обзором учителя, опросом ученика и после сохранения, если сервер сообщил
     о новой версии чужого слоя. */
  Widget.prototype.reload = function () {
    var self = this;
    if (!this.loaded || this.reloading) return Promise.resolve(false);
    this.reloading = true;
    var headers = {'X-Requested-With': 'XMLHttpRequest'};
    if (this.etag) headers['If-None-Match'] = this.etag;
    return fetch(this.url, {credentials: 'same-origin', headers: headers})
      .then(function (r) {
        if (r.status === 304) return null;
        return r.json().then(function (data) { self.etag = r.headers.get('ETag'); return data; });
      })
      .then(function (data) {
        if (!data || !data.ok) return false;
        return self.merge(data);
      }).catch(function () { return false; })
      .finally(function () { self.reloading = false; });
  };

  Widget.prototype.merge = function (data) {
    var self = this, changed = false, current = this.page();
    /* Права меняются вместе со статусом работы (отправил, вернули): новый слой
       или право добавлять страницы — повод пересобрать панель, даже если
       страницы те же */
    var layer = this.role === 'viewer' ? null : data.layer;
    var canAdd = data.can_add_pages !== false;
    if (layer !== this.layer || canAdd !== this.canAddPages) {
      this.layer = layer; this.canAddPages = canAdd; changed = true;
    }
    if (!!data.show_teacher_layer !== this.showTeacherLayer) { this.showTeacherLayer = !!data.show_teacher_layer; changed = true; }
    var other = this.layer === 'teacher' ? 'student' : 'teacher';
    /* Страницы, которых на сервере больше нет (удалили в другой вкладке), убираем —
       кроме ещё не сохранённых локальных заготовок и несохранённых правок */
    var known = {};
    data.pages.forEach(function (raw) { known[raw.number] = true; });
    for (var k = this.pages.length - 1; k >= 0; k--) {
      var gone = this.pages[k];
      var unsaved = gone.dirty || gone.saving || (!gone.layers.student.version && !gone.layers.teacher.version);
      if (known[gone.number] || unsaved) continue;
      this.pages.splice(k, 1);
      changed = true;
    }
    if (this.index >= this.pages.length) this.index = Math.max(0, this.pages.length - 1);
    data.pages.forEach(function (raw, i) {
      var page = self.pages[i];
      if (!page) {
        page = self.makePage(raw);
        self.pages.push(page);
        changed = true;
        return;
      }
      if (page.number !== raw.number) return;
      var incoming = raw[other];
      if (incoming && incoming.version !== page.layers[other].version) {
        page.layers[other] = {elements: incoming.elements, version: incoming.version};
        if (page !== current) page.fresh = true;
        changed = true;
      }
      /* Без своего слоя (просмотр) обновляем оба; свой слой не трогаем никогда */
      if (!self.layer && raw.student && raw.student.version !== page.layers.student.version) {
        page.layers.student = {elements: raw.student.elements, version: raw.student.version};
        changed = true;
      }
      if (page.createdBy !== self.layer) {
        if (page.background !== raw.background || JSON.stringify(page.bgOptions) !== JSON.stringify(raw.background_options || {})) {
          page.background = raw.background; page.bgOptions = raw.background_options || {};
          changed = true;
        }
      }
      if (page.locked !== !!raw.locked) { page.locked = !!raw.locked; changed = true; }
    });
    if (!changed) return false;
    this.updateNonEmpty();
    if (this.built) {
      /* Посреди штриха или недостроенной фигуры панель не пересобираем */
      if (this.drag || this.pending.length) this.redraw(); else this.refresh();
    }
    return true;
  };

  /* Опрос раз в POLL: только у ученика с открытой доской и видимой вкладкой —
     учитель на странице проверки получает reload() от живого обзора. */
  Widget.prototype.polls = function () {
    return this.role === 'student' && this.loaded && this.built && !this.root.hidden
      && !document.hidden && this.showTeacherLayer;
  };

  Widget.prototype.applyData = function (data) {
    var self = this;
    this.layer = this.role === 'viewer' ? null : data.layer;
    this.limits = data.limits || {student: 5, teacher: 2, total: 10, elements: 2000};
    this.showTeacherLayer = !!data.show_teacher_layer;
    this.canAddPages = data.can_add_pages !== false;
    this.images = data.images || [];
    this.pages = data.pages.map(function (raw) { return self.makePage(raw); });
    while (this.canAddPage()) {
      var page = this.makePage({number: this.pages.length + 1, created_by_role: this.layer});
      var backup = null;
      try { backup = JSON.parse(localStorage.getItem(this.backupKey(page, this.layer))); } catch (e) {}
      if (!backup || backup.version !== 0 || !Array.isArray(backup.elements)) break;
      this.pages.push(page);
    }
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
    if (!this.layer || this.canAddPages === false) return false;
    var pages = this.pages;
    if (pages.length >= this.limits.total) return false;
    if (this.layer === 'student') {
      return pages.filter(function (p) { return !p.locked && p.createdBy === 'student'; }).length < this.limits.student;
    }
    return pages.filter(function (p) { return p.createdBy === 'teacher'; }).length < this.limits.teacher;
  };

  Widget.prototype.addPage = function () {
    if (!this.canAddPage() || this.removing) return;
    var previous = this.pages[this.pages.length - 1];
    var page = this.makePage({number: this.pages.length + 1, created_by_role: this.layer,
      background: previous ? previous.background : 'grid',
      background_options: Object.assign({}, previous ? previous.bgOptions : {}, {square: true})});
    this.pages.push(page);
    this.touch(page);
    this.index = this.pages.length - 1;
    this.selection = [];
    this.pending = [];
    if (this.built) this.refresh();
  };

  Widget.prototype.removeLastPage = function () {
    var self = this, page = this.pages[this.pages.length - 1];
    if (this.removing || !page || !this.editableLayer(page)) return Promise.resolve(false);
    if (page.layers.student.elements.length || page.layers.teacher.elements.length) return Promise.resolve(false);
    this.removing = true;
    this.root.classList.add('canvas-busy');
    return this.flush(page).then(function (ok) {
      if (!ok) return false;
      return fetch(self.url + page.number + '/delete/', {
        method: 'POST', credentials: 'same-origin',
        headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (!data.ok) { toast(false, data.message || 'Не удалось удалить страницу'); return false; }
        clearTimeout(page.timer);
        self.dropBackup(page, self.layer);
        self.pages.pop();
        self.index = Math.max(0, self.pages.length - 1);
        self.updateNonEmpty();
        self.selection = []; self.pending = [];
        self.refresh();
        if (!self.pages.length) self.close();
        return true;
      });
    }).catch(function () { toast(false, 'Нет связи — страница не удалена'); return false; })
      .finally(function () { self.removing = false; self.root.classList.remove('canvas-busy'); });
  };

  Widget.prototype.syncDeleteButton = function () {
    if (!this.deletePageButton) return;
    var last = this.pages[this.pages.length - 1];
    var empty = last && !last.layers.student.elements.length && !last.layers.teacher.elements.length;
    this.deletePageButton.disabled = !last || !this.editableLayer(last) || !empty;
    this.deletePageButton.title = !last ? 'Страниц нет' : !this.editableLayer(last)
      ? 'Отправленную страницу нельзя удалить' : !empty
      ? 'Сначала очистите последнюю страницу' : 'Удалить пустую последнюю страницу';
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
      this.resizeObserver = new ResizeObserver(function () { self.resize(); });
      this.resizeObserver.observe(this.stage);
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
    tabs.appendChild(el('span', 'canvas-label', 'Доска для записей'));
    this.pages.forEach(function (p, i) {
      var b = button('btn btn-small btn-secondary canvas-page', String(p.number),
        p.locked ? 'Страница отправлена — только просмотр' : 'Страница ' + p.number, function () {
          self.switchPage(i);
        });
      b.setAttribute('aria-pressed', String(i === self.index));
      if (p.locked) b.classList.add('canvas-page-locked');
      if (p.fresh && i !== self.index) { b.classList.add('canvas-page-fresh'); b.title += ' — есть новые пометки'; }
      tabs.appendChild(b);
    });
    if (this.canAddPage()) {
      var limitHint = this.layer === 'teacher' ? 'до ' + this.limits.teacher + ' страниц учителя' : 'до ' + this.limits.student + ' страниц';
      tabs.appendChild(button('btn btn-small btn-secondary', '+', 'Добавить страницу (' + limitHint + ')', function () { self.addPage(); }));
    }
    this.deletePageButton = iconButton('trash', 'Удалить пустую последнюю страницу', function () { self.removeLastPage(); });
    if (this.layer) tabs.appendChild(this.deletePageButton);
    this.syncDeleteButton();
    head.appendChild(tabs);
    head.appendChild(button('icon-btn canvas-close', '×', 'Свернуть доску для записей — всё уже сохранено, откроется той же кнопкой', function () { self.close(); }));
    if (!page) {
      head.appendChild(el('span', 'helptext', this.layer ? 'Нажмите «+», чтобы добавить страницу.' : 'Страниц нет.'));
      this.toolbar.innerHTML = '';
      this.stage.hidden = true;
      return;
    }
    this.stage.hidden = false;
    var editable = this.editableLayer(page);

    var controls = el('div', 'canvas-controls');
    /* Фон — свойство страницы того, кто её создал: ученик правит свои страницы,
       учитель — свои; чужие страницы и просмотр получают одну подпись вместо
       трёх выпадающих списков. */
    var ownsBackground = !!this.layer && page.createdBy === this.layer;
    if (!ownsBackground) {
      var plane0 = page.background === 'plane';
      var desc = BG_LABELS[page.background] || page.background;
      if (plane0) {
        desc += ', ' + ((page.bgOptions.cell || 25) === 50 ? 'крупная клетка' : 'мелкая клетка')
          + ', ' + (page.bgOptions.origin === 'bottom_left' ? 'начало слева внизу' : 'начало в центре');
      }
      controls.appendChild(el('span', 'canvas-bg-note', 'Фон: ' + desc.toLowerCase()));
    }
    function labelled(text, select) {
      var label = el('label', 'canvas-bg-field');
      label.appendChild(el('span', null, text));
      label.appendChild(select);
      return label;
    }
    var bg = el('select', 'canvas-bg');
    Object.keys(BG_LABELS).forEach(function (key) {
      var opt = el('option', null, BG_LABELS[key]);
      opt.value = key;
      bg.appendChild(opt);
    });
    bg.value = page.background;
    bg.disabled = !editable;
    bg.title = 'Фон страницы: белый, клетка, крупная клетка или координатная плоскость';
    bg.addEventListener('change', function () {
      page.background = bg.value;
      if (bg.value === 'plane' && !page.bgOptions.cell) page.bgOptions = Object.assign({}, page.bgOptions, {cell: 50, origin: 'center'});
      self.touch(page);
      self.refresh();
    });
    if (ownsBackground) controls.appendChild(labelled('Фон', bg));
    var plane = page.background === 'plane';
    var cellSel = el('select', 'canvas-bg');
    [[25, 'мелкая клетка'], [50, 'крупная клетка']].forEach(function (pair) {
      var opt = el('option', null, pair[1]); opt.value = String(pair[0]); cellSel.appendChild(opt);
    });
    cellSel.value = String(page.bgOptions.cell || 25);
    /* На старых страницах 1000×750 клетка задаёт смещение рисунка (offsetOf) — там её не меняем */
    var legacy = !page.bgOptions.square;
    cellSel.disabled = !editable || !plane || legacy;
    cellSel.title = !plane ? 'Размер клетки — только для координатной плоскости'
      : legacy ? 'На странице старого формата размер клетки фиксирован' : 'Размер клетки координатной плоскости';
    cellSel.addEventListener('change', function () {
      page.bgOptions = Object.assign({}, page.bgOptions, {cell: parseInt(cellSel.value, 10)});
      self.touch(page); self.redraw();
    });
    if (ownsBackground) controls.appendChild(labelled('Клетка', cellSel));
    var originSel = el('select', 'canvas-bg');
    [['center', 'начало в центре'], ['bottom_left', 'начало слева внизу']].forEach(function (pair) {
      var opt = el('option', null, pair[1]); opt.value = pair[0]; originSel.appendChild(opt);
    });
    originSel.value = page.bgOptions.origin || 'center';
    originSel.disabled = !editable || !plane;
    originSel.title = plane ? 'Положение начала координат: в центре или слева внизу (для парабол и корней)' : 'Начало координат — только для координатной плоскости';
    originSel.addEventListener('change', function () {
      page.bgOptions = Object.assign({}, page.bgOptions, {origin: originSel.value});
      self.touch(page); self.redraw();
    });
    if (ownsBackground) controls.appendChild(labelled('Начало координат', originSel));
    if (this.role === 'student' && this.showTeacherLayer) {
      var teacherToggle = this.toggle('Скрыть пометки учителя', !this.showTeacher, function (hide) {
        self.showTeacher = !hide;
        try { localStorage.setItem(HIDE_TEACHER_KEY, hide ? '1' : '0'); } catch (e) {}
        self.redraw();
      });
      teacherToggle.title = 'Пометки учителя появляются поверх вашего решения по мере того, как он их оставляет; тумблер их прячет';
      controls.appendChild(teacherToggle);
    }
    if (page.locked && this.role === 'student') {
      controls.appendChild(el('span', 'helptext', 'Страница отправлена — только просмотр'));
    }
    head.appendChild(controls);

    this.selection = [];
    this.pending = [];
    this.buildToolbar(editable);
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

  /* Панель строится один раз на страницу и больше не перестраивается: набор
     кнопок, их число и порядок не зависят от инструмента и выделения, меняются
     только aria-pressed/disabled и цвета слотов. Иначе появление ряда с
     действиями над выделением сдвигало бы рабочее поле. */
  Widget.prototype.buildToolbar = function (editable) {
    var self = this, bar = this.toolbar;
    bar.innerHTML = '';
    this.toolButtons = {};
    this.swatches = [];
    this.widthButtons = [];
    this.selectionButtons = [];
    if (!editable) {
      /* Только просмотр: единственная кнопка — скопировать картинкой */
      var view = el('div', 'canvas-toolbar-row');
      view.appendChild(iconButton('copy', 'Скопировать страницу как картинку — вставится в чат, документ или презентацию', function () { self.copyPage(); }));
      bar.appendChild(view);
      return;
    }
    var page = this.page();
    var row1 = el('div', 'canvas-toolbar-row'), row2 = el('div', 'canvas-toolbar-row');
    bar.appendChild(row1);
    bar.appendChild(row2);
    function group(row, cls) { var g = el('div', 'canvas-group' + (cls ? ' ' + cls : '')); row.appendChild(g); return g; }
    function tool(container, name, text, title) {
      var b = button('btn btn-small btn-secondary canvas-tool', text, title, function () { self.setTool(name); });
      if (ICONS[name]) addIcon(b, name);
      b.dataset.tool = name;
      container.appendChild(b);
      self.toolButtons[name] = b;
      return b;
    }
    var main = group(row1);
    tool(main, 'pen', 'Карандаш', 'Карандаш (P)');
    tool(main, 'hl', 'Маркер', 'Маркер — полупрозрачный выделитель (Shift+P)');
    tool(main, 'eraser', 'Ластик', 'Ластик: стирает участки карандаша и маркера; фигуры удаляются через «Выбор» (E)');
    tool(main, 'select', 'Выбор', 'Выбор: клик или рамка выделяет, перетаскивание двигает, стрелки сдвигают на 1 (с Shift — на 10), Esc снимает выделение (V)');

    var shapes = group(row1);
    Object.keys(SHAPE_TOOLS).forEach(function (name) { tool(shapes, name, SHAPE_TOOLS[name].label, SHAPE_TOOLS[name].title); });

    var graphs = group(row1, 'canvas-graphs');
    Object.keys(FN).forEach(function (kind) {
      var graph = button('btn btn-small btn-secondary canvas-tool', FN[kind].label,
        FN[kind].title + ' — вставить заготовку текущим цветом и толщиной; опорную точку и ручку (1; 1) можно тянуть в режиме «Выбор»', function () {
        self.insertFn(kind);
      });
      if (window.katex) window.katex.render({parabola: 'x^2', abs: '|x|', sqrt: '\\sqrt{x}', hyperbola: '1/x'}[kind], graph, {throwOnError: false});
      graphs.appendChild(graph);
    });
    var pictures = group(row1, 'canvas-pictures');
    this.imageButton = button('btn btn-small btn-secondary canvas-tool', 'Рисунок', 'Вставить рисунок из условия задачи', function () { self.pickImage(self.imageButton); });
    if (ICONS.image) addIcon(this.imageButton, 'image');
    pictures.appendChild(this.imageButton);

    var history = group(row1);
    this.undoButton = iconButton('undo', 'Отменить (Ctrl+Z, на Mac ⌘Z)', function () { self.undo(); });
    this.redoButton = iconButton('redo', 'Вернуть (Ctrl+Shift+Z или Ctrl+Y)', function () { self.redo(); });
    history.appendChild(this.undoButton);
    history.appendChild(this.redoButton);
    history.appendChild(iconButton('clear', 'Очистить страницу — свой слой целиком; отменяется через Ctrl+Z', function () { self.clearPage(); }));
    history.appendChild(iconButton('copy', 'Скопировать страницу как картинку — вставится в чат, документ или презентацию', function () { self.copyPage(); }));

    var colors = group(row2, 'canvas-colors');
    COLORS.forEach(function (_, i) {
      var b = button('canvas-swatch', '', 'Цвет', function () {
        var c = self.paletteFor().colors[i];
        if (self.tool === 'hl') self.hlColor = c; else self.color = c;
        self.recolorSelection(c);
        self.syncToolbar();
      });
      colors.appendChild(b);
      self.swatches.push(b);
    });

    var widths = group(row2, 'canvas-widths');
    PEN_WIDTHS.forEach(function (_, i) {
      var b = button('canvas-width', '', 'Толщина', function () {
        var w = self.paletteFor().widths[i];
        if (self.tool === 'hl') self.hlWidth = w; else if (self.tool === 'eraser') self.eraserSize = w; else self.penWidth = w;
        self.rewidthSelection(w);
        self.syncToolbar();
      });
      var dot = el('span');
      dot.style.width = dot.style.height = (6 + i * 5) + 'px';
      b.appendChild(dot);
      widths.appendChild(b);
      self.widthButtons.push(b);
    });

    var sel = group(row2, 'canvas-selection');
    [['trash', 'Удалить выделенное (Delete или Backspace)', function () { self.deleteSelection(); }],
     ['group', 'Сгруппировать выделенное: двигается и выделяется вместе (Ctrl+G)', function () { self.groupSelection(true); }],
     ['ungroup', 'Разгруппировать (Ctrl+Shift+G)', function () { self.groupSelection(false); }],
     ['front', 'На передний план (клавиша ])', function () { self.reorderSelection(true); }],
     ['back', 'На задний план (клавиша [)', function () { self.reorderSelection(false); }]].forEach(function (item) {
      var b = iconButton(item[0], item[1], item[2]);
      b.classList.remove('icon-btn');
      b.classList.add('btn', 'btn-small', 'btn-secondary');
      sel.appendChild(b);
      self.selectionButtons.push(b);
    });

    var misc = group(row2);
    this.snapToggle = this.toggle('Привязывать к сетке', this.snap, function (on) { self.snap = on; });
    this.snapToggle.title = 'Концы фигур, точки и ручки заготовок притягиваются к узлам сетки; карандаша не касается';
    misc.appendChild(this.snapToggle);
    this.syncToolbar();
  };

  /* Палитра и толщины текущего инструмента (слотов всегда поровну) */
  Widget.prototype.paletteFor = function () {
    if (this.tool === 'hl') return {colors: HL_COLORS, widths: HL_WIDTHS, current: this.hlColor, width: this.hlWidth};
    if (this.tool === 'eraser') return {colors: COLORS, widths: ERASER_SIZES, current: null, width: this.eraserSize};
    return {colors: COLORS, widths: PEN_WIDTHS, current: this.color, width: this.penWidth};
  };

  Widget.prototype.syncToolbar = function () {
    var self = this, page = this.page();
    if (!page || !this.toolButtons) return;
    Object.keys(this.toolButtons).forEach(function (name) {
      self.toolButtons[name].setAttribute('aria-pressed', String(self.tool === name));
    });
    var palette = this.paletteFor();
    this.swatches.forEach(function (b, i) {
      var c = palette.colors[i];
      b.style.setProperty('--c', c);
      b.title = self.tool === 'eraser' ? 'У ластика нет цвета'
        : 'Цвет: ' + (COLOR_NAMES[c] || c) + (self.selection.length ? ' — перекрасить выделенное' : '');
      b.setAttribute('aria-label', b.title);
      b.disabled = self.tool === 'eraser';
      b.setAttribute('aria-pressed', String(c === palette.current));
    });
    this.widthButtons.forEach(function (b, i) {
      var w = palette.widths[i];
      b.title = self.tool === 'eraser' ? 'Размер ластика: ' + ERASER_NAMES[i] + ' (' + w + ')'
        : 'Толщина: ' + SIZE_NAMES[i] + ' (' + w + ')' + (self.selection.length ? ' — применить к выделенному' : '');
      b.setAttribute('aria-label', b.title);
      b.setAttribute('aria-pressed', String(w === palette.width));
    });
    if (this.imageButton) {
      var n = (this.images || []).length;
      this.imageButton.disabled = !n;
      this.imageButton.title = n ? 'Вставить рисунок из условия задачи' + (n > 1 ? ' (' + n + ')' : '')
        : 'У этой задачи нет рисунков, которые можно положить на доску';
      this.imageButton.setAttribute('aria-label', this.imageButton.title);
    }
    var hasSelection = this.tool === 'select' && this.selection.length > 0;
    this.selectionButtons.forEach(function (b, i) {
      b.disabled = !hasSelection || (i === 1 && self.selection.length < 2);
    });
    if (this.undoButton) this.undoButton.disabled = !page.undo.length;
    if (this.redoButton) this.redoButton.disabled = !page.redo.length;
    if (this.snapToggle) {
      var input = this.snapToggle.querySelector('input');
      input.disabled = !cellOf(page);
      this.snapToggle.classList.toggle('canvas-disabled', !cellOf(page));
    }
  };

  Widget.prototype.setTool = function (name) {
    this.tool = name;
    this.pending = [];
    if (name !== 'select') this.selection = [];
    this.syncToolbar();
    this.drawTop();
  };

  Widget.prototype.switchPage = function (i) {
    if (i === this.index) return;
    this.flush(this.page());
    this.index = i;
    this.pages[i].fresh = false;
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
    this.redraw();
  };

  Widget.prototype.context = function (canvas) {
    var ctx = canvas.getContext('2d'), dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr * this.scale, 0, 0, dpr * this.scale, 0, offsetOf(this.page()) * dpr * this.scale);
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
    var self = this, page = this.page();
    if (page) {
      if (!this.awaited) this.awaited = {};
      pendingImages(page.layers.student.elements.concat(page.layers.teacher.elements)).forEach(function (url) {
        if (self.awaited[url]) return;
        self.awaited[url] = true;
        whenImageSettles(url, function () {
          delete self.awaited[url];
          if (document.body.contains(self.root)) self.redraw();
        });
      });
    }
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
    ctx.clearRect(0, -offsetOf(page), W, H);
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
    ctx.clearRect(0, -offsetOf(page), W, H);
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
      if (selected.length === 1 && selected[0].t === 'img') {
        var img = drag && drag.kind === 'handle' && drag.preview ? drag.preview : selected[0];
        var hc = imgCorners(img), hs = imgHandles(img), r = 7 / this.scale * Math.min(this.scale, 1) + 3;
        ctx.strokeStyle = ACCENT; ctx.lineWidth = 1.5; ctx.setLineDash([]);
        ctx.beginPath(); ctx.moveTo(hc[0][0], hc[0][1]);
        for (var hq = 1; hq < 4; hq++) ctx.lineTo(hc[hq][0], hc[hq][1]);
        ctx.closePath(); ctx.stroke();
        var topMid = hs[4].at, rotAt = hs[8].at;
        ctx.beginPath(); ctx.moveTo(topMid[0], topMid[1]); ctx.lineTo(rotAt[0], rotAt[1]); ctx.stroke();
        hs.forEach(function (h) {
          ctx.fillStyle = h.kind === 'rotate' ? ACCENT : '#fff'; ctx.strokeStyle = ACCENT; ctx.lineWidth = 2;
          ctx.beginPath();
          if (h.kind === 'side') ctx.rect(h.at[0] - r * 0.8, h.at[1] - r * 0.8, r * 1.6, r * 1.6);
          else ctx.arc(h.at[0], h.at[1], r, 0, Math.PI * 2);
          ctx.fill(); ctx.stroke();
        });
      }
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
    if (!layer || this.removing) return;
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
    this.syncDeleteButton();
    this.syncToolbar();
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
      if (self.selection.indexOf(e.id) < 0) return e;
      return Object.assign({}, e, {c: color});
    }));
    this.redraw();
  };

  Widget.prototype.rewidthSelection = function (width) {
    var page = this.page(), self = this;
    if (!this.selection.length || this.tool !== 'select') return;
    this.commit(page, this.ownElements(page).map(function (element) {
      return self.selection.indexOf(element.id) < 0 ? element : Object.assign({}, element, {w: width});
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

  /* Иллюстрация задачи на доску: ширина 400 логических px, в центре видимой
     страницы; сразу выделена, дальше — ручки */
  Widget.prototype.insertImage = function (image) {
    var self = this, page = this.page();
    if (!page || !this.editableLayer(page)) return;
    var place = function (entry) {
      if (entry.failed) { toast(false, 'Не удалось загрузить рисунок'); return; }
      var iw = entry.img.naturalWidth || 4, ih = entry.img.naturalHeight || 3;
      var w = Math.min(400, iw), h = Math.round(w * ih / iw);
      var cx = W / 2, cy = H / 2 - offsetOf(page);
      var tl = [Math.round(cx - w / 2), Math.round(cy - h / 2)];
      var element = {id: uid(), t: 'img', s: image.id, u: image.url, c: '#000000', w: 1,
        p: [tl, [tl[0] + w, tl[1]], [tl[0], tl[1] + h]]};
      self.addElement(element);
      self.tool = 'select';
      self.selection = [element.id];
      self.syncToolbar();
      self.drawTop();
    };
    whenImageSettles(image.url, place);
  };

  Widget.prototype.pickImage = function (anchor) {
    var self = this, images = this.images || [];
    if (!images.length) return;
    if (images.length === 1) { this.insertImage(images[0]); return; }
    var old = this.root.querySelector('.canvas-menu');
    if (old) { old.remove(); return; }
    var menu = el('div', 'canvas-menu');
    images.forEach(function (image, i) {
      var b = button('canvas-menu-item', '', 'Вставить рисунок ' + (i + 1), function () { menu.remove(); self.insertImage(image); });
      var thumb = el('img'); thumb.src = image.url; thumb.alt = 'рисунок ' + (i + 1); thumb.loading = 'lazy';
      b.appendChild(thumb);
      menu.appendChild(b);
    });
    anchor.parentNode.appendChild(menu);
    setTimeout(function () {
      document.addEventListener('pointerdown', function close(ev) {
        if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener('pointerdown', close); }
      });
    }, 0);
  };

  Widget.prototype.insertFn = function (kind) {
    var page = this.page();
    if (!page || !this.editableLayer(page)) return;
    var cell = cellOf(page) || 25;
    var o = page.background === 'plane' ? planeOrigin(page) : [W / 2, H / 2 - offsetOf(page)];
    var element = {id: uid(), t: 'fn', k: kind, c: this.color, w: this.penWidth, p: [[o[0], o[1]], [o[0] + cell, o[1] - cell]]};
    this.addElement(element);
    this.tool = 'select';
    this.selection = [element.id];
    this.syncToolbar();
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
    return [(e.clientX - rect.left) / this.scale, (e.clientY - rect.top) / this.scale - offsetOf(this.page())];
  };

  Widget.prototype.snapped = function (pt) {
    var page = this.page(), cell = cellOf(page);
    if (!this.snap || !cell) return pt;
    var o = page.background === 'plane' ? planeOrigin(page) : [0, 0];
    return [o[0] + Math.round((pt[0] - o[0]) / cell) * cell, o[1] + Math.round((pt[1] - o[1]) / cell) * cell];
  };

  Widget.prototype.onDown = function (e) {
    var page = this.page();
    if (!page || !this.editableLayer(page) || this.drag || this.removing) return;
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
    var additive = e.shiftKey || e.ctrlKey || e.metaKey;
    var selected = this.selectedElements();
    if (!additive && selected.length === 1 && selected[0].t === 'img') {
      var img = selected[0], grab = 11 / this.scale, handlesOfImg = imgHandles(img);
      for (var h = handlesOfImg.length - 1; h >= 0; h--) {
        if (dist(handlesOfImg[h].at, pt) <= grab) {
          this.drag = {kind: 'handle', pointerId: e.pointerId, element: img, handle: handlesOfImg[h], start: pt, preview: null};
          return;
        }
      }
    }
    if (!additive && selected.length === 1 && selected[0].t === 'fn') {
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
      if (this.selection.indexOf(hit.id) < 0 || additive) this.select(hit, additive);
      var ids = {};
      this.selection.forEach(function (id) { ids[id] = true; });
      this.drag = {kind: 'move', pointerId: e.pointerId, from: pt, dx: 0, dy: 0, ids: ids};
    } else {
      if (!additive) this.selection = [];
      this.drag = {kind: 'band', pointerId: e.pointerId, from: pt, to: pt, add: additive};
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
        if (drag.handle) {
          drag.preview = imgTransform(drag.element, drag.handle, drag.start, pt, e.shiftKey);
          this.redraw();
          return;
        }
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
    if (cancelled) {
      if (drag.kind === 'erase') page.layers[this.editableLayer(page)].elements = drag.before;
      this.redraw(); return;
    }
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
          var ids = {};
          if (drag.add) this.selection.forEach(function (id) { ids[id] = true; });
          picked.forEach(function (el) { ids[el.id] = true; });
          this.selection = this.ownElements(page).filter(function (el) {
            return ids[el.id] || (el.g && picked.some(function (p) { return p.g === el.g; }));
          }).map(function (el) { return el.id; });
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
    if (!widget || !widget.built || widget.root.hidden || widget.removing) return;
    var target = e.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable || target.tagName === 'MATH-FIELD')) return;
    var page = widget.page();
    if (!page || !widget.editableLayer(page)) return;
    /* e.code — физическая клавиша: латинская P и кириллическая З — одна кнопка,
       так что подсказки «P», «E», «V» верны в любой раскладке; e.key — запас
       для клавиатур без кода (экранные, некоторые Android) */
    var key = e.key, code = e.code || '', mod = e.ctrlKey || e.metaKey;
    var latin = code.indexOf('Key') === 0 ? code.slice(3).toLowerCase() : '';
    if (!latin) {
      var byKey = {я: 'z', п: 'g', н: 'y', м: 'v', р: 'h', з: 'p', у: 'e', щ: 'o', ы: 's', д: 'l'};
      latin = byKey[key.toLowerCase()] || (/^[a-z]$/i.test(key) ? key.toLowerCase() : '');
    }
    if (mod && latin === 'z') { e.preventDefault(); if (e.shiftKey) widget.redo(); else widget.undo(); return; }
    if (mod && latin === 'y') { e.preventDefault(); widget.redo(); return; }
    if (mod && latin === 'g') { e.preventDefault(); widget.groupSelection(!e.shiftKey); return; }
    if (mod) return;
    if (key === 'Escape') { widget.pending = []; widget.selection = []; widget.syncHistoryButtons(page); widget.redraw(); return; }
    if (key === 'Delete' || key === 'Backspace') { if (widget.selection.length) { e.preventDefault(); widget.deleteSelection(); } return; }
    if (key === ']' || code === 'BracketRight') { widget.reorderSelection(true); return; }
    if (key === '[' || code === 'BracketLeft') { widget.reorderSelection(false); return; }
    if (key.indexOf('Arrow') === 0 && widget.selection.length) {
      e.preventDefault();
      var step = e.shiftKey ? 10 : 1;
      widget.moveSelection(key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0,
                           key === 'ArrowUp' ? -step : key === 'ArrowDown' ? step : 0);
      return;
    }
    var tools = {v: 'select', h: 'select', p: 'pen', e: 'eraser', o: 'rect', s: 'circle', l: 'line'};
    var name = latin === 'p' && e.shiftKey ? 'hl' : tools[latin];
    if (name) { e.preventDefault(); widget.setTool(name); }
  });

  /* ---------- сохранение ---------- */

  Widget.prototype.touch = function (page) {
    var self = this;
    page.rev++;
    page.dirty = true;
    this.updateNonEmpty();
    var layer = this.editableLayer(page);
    if (layer) this.storeBackup(page, layer);
    if (!page.firstDirtyAt) page.firstDirtyAt = Date.now();
    clearTimeout(page.timer);
    var wait = Date.now() - page.firstDirtyAt >= MAX_WAIT ? 0 : DEBOUNCE;
    page.timer = setTimeout(function () { self.save(page); }, wait);
  };

  Widget.prototype.updateNonEmpty = function () {
    var any = this.pages.some(function (p) { return p.layers.student.elements.length; });
    this.root.dataset.nonempty = any ? '1' : '';
  };

  Widget.prototype.body = function (page, layer) {
    return JSON.stringify({
      layer: layer, elements: page.layers[layer].elements, version: page.layers[layer].version,
      background: page.background, background_options: page.bgOptions,
    });
  };

  Widget.prototype.flush = function (page) {
    var self = this;
    if (!page) return Promise.resolve(true);
    var pending = page.saving ? page.savePromise : this.save(page);
    return pending.then(function (ok) {
      if (!ok) return false;
      return page.dirty ? self.flush(page) : true;
    });
  };

  Widget.prototype.flushAll = function () {
    var self = this;
    // Страницы создаются по порядку, включая пустые промежуточные.
    return this.pages.reduce(function (promise, page) {
      return promise.then(function (ok) { return ok ? self.flush(page) : false; });
    }, Promise.resolve(true));
  };

  Widget.prototype.save = function (page) {
    var self = this, layer = this.editableLayer(page);
    clearTimeout(page.timer);
    if (!page.dirty) return Promise.resolve(true);
    if (!layer) return Promise.resolve(false);
    if (page.saving) return page.savePromise;
    var previous = this.pages[this.pages.indexOf(page) - 1];
    if (previous && !previous.layers.student.version && !previous.layers.teacher.version) {
      return this.flush(previous).then(function (ok) { return ok ? self.save(page) : false; });
    }
    page.saving = true;
    var rev, body;
    var enqueue = window.EgorAutosave && EgorAutosave.enqueue || function (_, operation) { return operation(); };
    page.savePromise = enqueue(this, function () {
      rev = page.rev;
      body = self.body(page, layer);
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
        var other = layer === 'teacher' ? 'student' : 'teacher';
        if (typeof data.other_version === 'number' && data.other_version !== page.layers[other].version) self.reload();
        if (page.rev === rev) {
          page.dirty = false; page.firstDirtyAt = 0;
          self.dropBackup(page, layer);
        } else self.storeBackup(page, layer);
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
      } else {
        self.storeBackup(page, layer);
        toast(false, data.message || 'Ошибка сохранения');
      }
      if (data.ok && page.dirty) {
        clearTimeout(page.timer);
        page.timer = setTimeout(function () { self.save(page); }, DEBOUNCE);
      }
      return !!data.ok;
    }).catch(function () {
      page.saving = false;
      self.storeBackup(page, layer);
      var delay = RETRY[Math.min(page.retry, RETRY.length - 1)];
      page.retry++;
      toast(false, 'Нет связи — доска для записей не сохранена, повторю через ' + Math.round(delay / 1000) + ' с');
      page.timer = setTimeout(function () { self.save(page); }, delay);
      return false;
    });
    return page.savePromise;
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
        if (!page.saving && body.length < KEEPALIVE_LIMIT && typeof fetch === 'function') {
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

  /* Перед отправкой задания и возвратом проверки ждём все слои.
     При ошибке форма остаётся открытой вместе с локальным черновиком. */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    var widgets = Widget.all.filter(function (w) { return form.contains(w.root); });
    if (!widgets.length || form.dataset.canvasFlushed) return;
    var dirty = widgets.some(function (w) { return w.pages.some(function (p) { return p.dirty || p.saving; }); });
    if (!dirty) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (form.dataset.canvasFlushing) return;
    form.dataset.canvasFlushing = '1';
    var submitter = e.submitter;
    Promise.all(widgets.map(function (w) { return w.flushAll(); })).then(function (results) {
      delete form.dataset.canvasFlushing;
      if (!results.every(Boolean)) {
        toast(false, 'Доска для записей не сохранена — повторите отправку после сохранения');
        return;
      }
      form.dataset.canvasFlushed = '1';
      try { form.requestSubmit(submitter || undefined); }
      finally { delete form.dataset.canvasFlushed; }
    });
  }, true);

  /* ---------- инициализация ---------- */

  Widget.all = [];
  Widget.penSeen = false;
  Widget.active = null;

  function init(root) {
    if (root.canvasWidget || !root.dataset.url) return;
    if (root.dataset.role === 'viewer') {
      var editor = Array.from(document.querySelectorAll('[data-canvas][data-role="teacher"]'))
        .find(function (node) { return node.dataset.url === root.dataset.url; });
      if (editor) {
        root.hidden = true;
        if (editor.canvasWidget) editor.canvasWidget.reload();
        return;
      }
    }
    Widget.all.push(new Widget(root));
  }
  function initAll(scope) {
    (scope || document).querySelectorAll('[data-canvas]').forEach(init);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('toggle-canvas');
    if (toggle) {
      toggle.checked = Widget.showEnabled();
      toggle.addEventListener('change', function () {
        try { localStorage.setItem(SHOW_KEY, toggle.checked ? '1' : '0'); } catch (e) {}
        Widget.all.forEach(function (w) { if (w.role !== 'student' && !w.root.dataset.always) w.applyTeacherToggle(); });
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

  function pollAll() {
    Widget.all.forEach(function (w) { if (w.polls()) w.reload(); });
  }
  setInterval(pollAll, POLL);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) pollAll(); });

  /* Чистый рендер страницы в любой canvas (миниатюры дашборда «Доски»):
     без панели, обработчиков и undo. size — сторона в CSS-пикселях. */
  function renderPage(canvas, raw, size, pixelRatio) {
    var page = {
      background: raw.background || 'grid', bgOptions: raw.background_options || {},
      layers: {student: {elements: raw.student ? raw.student.elements : []},
               teacher: {elements: raw.teacher ? raw.teacher.elements : []}},
    };
    var dpr = pixelRatio || Math.min(window.devicePixelRatio || 1, 2), scale = size / W;
    canvas.width = Math.round(size * dpr); canvas.height = Math.round(size * dpr);
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, offsetOf(page) * dpr * scale);
    drawBackground(ctx, page);
    ['student', 'teacher'].forEach(function (name) {
      page.layers[name].elements.forEach(function (element) { drawElement(ctx, element, page); });
    });
    pendingImages(page.layers.student.elements.concat(page.layers.teacher.elements)).forEach(function (url) {
      whenImageSettles(url, function () { if (document.body.contains(canvas)) renderPage(canvas, raw, size, pixelRatio); });
    });
  }

  /* ---------- копирование доски картинкой ----------
     PNG 1500×1500 с фоном и обоими слоями — в буфер обмена, чтобы вставить
     в чат, документ или презентацию; без Clipboard API (или если браузер
     отказал) — скачивание файла. Картинки задач того же происхождения,
     поэтому canvas не «портится» и toBlob доступен. */
  var EXPORT_SIZE = 1500;
  function pageBlob(raw) {
    return new Promise(function (resolve, reject) {
      var urls = pendingImages((raw.student ? raw.student.elements : []).concat(raw.teacher ? raw.teacher.elements : []));
      var left = urls.length;
      var draw = function () {
        var canvas = document.createElement('canvas');
        renderPage(canvas, raw, EXPORT_SIZE, 1);
        canvas.toBlob(function (blob) { blob ? resolve(blob) : reject(new Error('toBlob')); }, 'image/png');
      };
      if (!left) { draw(); return; }
      urls.forEach(function (url) { whenImageSettles(url, function () { if (--left === 0) draw(); }); });
    });
  }
  function downloadBlob(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
  }
  function copyPage(raw, name) {
    var blobPromise = pageBlob(raw);
    if (navigator.clipboard && window.ClipboardItem) {
      var item;
      try {
        /* Safari требует создать ClipboardItem синхронно в жесте — отдаём Promise<Blob> */
        item = new ClipboardItem({'image/png': blobPromise});
      } catch (e) { item = null; }
      if (item) {
        return navigator.clipboard.write([item])
          .then(function () { toast(true, 'Доска скопирована как картинка'); return true; })
          .catch(function () {
            return blobPromise.then(function (blob) { downloadBlob(blob, name); toast(true, 'Буфер недоступен — картинка скачана'); return true; });
          });
      }
    }
    return blobPromise.then(function (blob) { downloadBlob(blob, name); toast(true, 'Картинка скачана'); return true; })
      .catch(function () { toast(false, 'Не удалось подготовить картинку'); return false; });
  }

  Widget.prototype.copyPage = function () {
    var page = this.page();
    if (!page) return;
    var raw = {background: page.background, background_options: page.bgOptions,
      student: {elements: page.layers.student.elements},
      teacher: {elements: this.visibleLayers(page).some(function (l) { return l.name === 'teacher'; }) ? page.layers.teacher.elements : []}};
    copyPage(raw, 'доска-стр-' + page.number + '.png');
  };

  window.EgorCanvas = {Widget: Widget, init: initAll, render: renderPage, copy: copyPage, blob: pageBlob,
    image: {corners: imgCorners, handles: imgHandles, transform: imgTransform, inside: insideParallelogram,
            of: imageOf, settle: whenImageSettles, pending: pendingImages}};
})();
