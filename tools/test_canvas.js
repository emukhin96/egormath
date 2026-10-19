/* Сохранение холста перед отправкой и восстановление локальных черновиков. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function setup() {
  const listeners = {}, storage = new Map(), calls = [], pending = [];
  const document = {
    addEventListener(name, callback) { listeners[name] = callback; },
    querySelector() { return null; }, cookie: '',
  };
  const context = {
    document, Promise, WeakMap, setTimeout() { return 1; }, clearTimeout() {}, setInterval() { return 1; },
    localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    addEventListener() {},
    fetch(url, options) {
      calls.push({url, body: options.body ? JSON.parse(options.body) : null});
      return new Promise((resolve, reject) => pending.push({
        resolve(status = 200, data = {ok: true, version: 1}) { resolve({status, json: async () => data}); }, reject,
      }));
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../public_html/static/js/canvas.js'), 'utf8'), context);
  const Widget = context.EgorCanvas.Widget;
  const widget = Object.assign(Object.create(Widget.prototype), {
    root: {dataset: {}, classList: {add() {}, remove() {}}}, url: '/assignments/1/canvas/1/', role: 'student', layer: 'student',
    pages: [], limits: {student: 5, teacher: 2, total: 10, elements: 2000},
    refresh() {}, redraw() {}, syncHistoryButtons() {},
  });
  Widget.all.push(widget);
  return {widget, listeners, storage, calls, pending, context};
}
const drain = () => new Promise(resolve => setImmediate(resolve));
const stroke = id => ({id, t: 'path', c: '#000000', w: 2, p: [[10, 10], [20, 20]]});

function submit(env) {
  const form = {dataset: {}, contains: root => root === env.widget.root, requestSubmit() { this.sent = true; }};
  env.listeners.submit({target: form, preventDefault() {}, stopImmediatePropagation() {}});
  return form;
}

test('отправка ждёт текущий запрос и штрихи, добавленные во время сохранения', async () => {
  const env = setup(), w = env.widget;
  w.addPage();
  const page = w.page();
  w.commit(page, [stroke('a')]);
  const first = w.save(page);
  w.commit(page, [stroke('a'), stroke('b')]);
  const form = submit(env);
  assert.equal(form.sent, undefined);
  env.pending.shift().resolve();
  await first; await drain();
  assert.equal(env.calls.length, 2);
  assert.equal(env.calls[1].body.version, 1);
  assert.equal(env.calls[1].body.elements.length, 2);
  assert.equal(form.sent, undefined);
  env.pending.shift().resolve(200, {ok: true, version: 2});
  await drain();
  assert.equal(form.sent, true);
  assert.equal(page.dirty, false);
});

test('сбой сети и отказ сервера блокируют отправку и сохраняют черновик', async () => {
  for (const status of [0, 400, 403, 413, 503]) {
    const env = setup(); env.widget.addPage();
    const form = submit(env);
    await drain();
    if (status) env.pending.shift().resolve(status, {ok: false});
    else env.pending.shift().reject(new Error('offline'));
    await drain();
    assert.equal(form.sent, undefined);
    assert.equal(env.widget.page().dirty, true);
    assert.equal(env.storage.size, 1);
  }
});

test('пустая первая страница сохраняется до второй', async () => {
  const env = setup(), w = env.widget;
  w.addPage(); w.addPage(); w.commit(w.page(), [stroke('b')]);
  const flushed = w.flushAll();
  await drain();
  assert.equal(env.calls[0].url, w.url + '1/');
  assert.equal(env.calls[0].body.elements.length, 0);
  env.pending.shift().resolve(); await drain();
  assert.equal(env.calls[1].url, w.url + '2/');
  env.pending.shift().resolve();
  assert.equal(await flushed, true);
});

test('ещё не созданные страницы восстанавливаются из локального черновика', () => {
  const env = setup(), w = env.widget;
  w.addPage(); w.addPage(); w.commit(w.page(), [stroke('b')]);
  w.applyData({layer: 'student', pages: [], limits: w.limits});
  assert.equal(w.pages.length, 2);
  assert.equal(w.pages[1].layers.student.elements[0].id, 'b');
  assert.equal(w.pages[1].dirty, true);
});

test('viewer не получает инструментов, даже когда учитель может редактировать', () => {
  const {widget: w} = setup();
  w.role = 'viewer';
  w.applyData({layer: 'teacher', pages: [{number: 1}], limits: w.limits});
  assert.equal(w.editableLayer(w.page()), null);
  assert.equal(w.canAddPage(), false);
});

test('отмена жеста ластика возвращает исходный штрих', () => {
  const {widget: w} = setup(); w.addPage();
  const before = [stroke('a')];
  w.page().layers.student.elements = [];
  w.stage = {releasePointerCapture() {}};
  w.drag = {kind: 'erase', pointerId: 1, before, changed: true};
  w.onUp({pointerId: 1}, true);
  assert.equal(w.page().layers.student.elements, before);
});

test('гипербола не соединяет ветви через асимптоту между отсчётами', () => {
  const {widget: w} = setup(); w.addPage();
  w.page().background = 'blank';
  w.page().layers.student.elements = [{id: 'f', t: 'fn', k: 'hyperbola', c: '#000000', w: 2, p: [[500, 375], [525, 350]]}];
  const lines = [];
  const ctx = {save() {}, restore() {}, clearRect() {}, fillRect() {}, beginPath() {}, stroke() {},
    moveTo(x, y) { lines.push([[x, y]]); }, lineTo(x, y) { lines[lines.length - 1].push([x, y]); }};
  w.scale = 1; w.context = () => ctx;
  w.drawBase();
  assert.equal(lines.length, 2);
  assert.ok(lines[0].every(([x]) => x < 500));
  assert.ok(lines[1].every(([x]) => x > 500));
});

test('автосохранение второй страницы сначала создаёт первую, даже если её таймер ещё не сработал', async () => {
  const env = setup(), w = env.widget;
  w.addPage(); w.addPage();
  const saved = w.save(w.page());
  assert.equal(env.calls[0].url, w.url + '1/');
  env.pending.shift().resolve(); await drain();
  assert.equal(env.calls[1].url, w.url + '2/');
  env.pending.shift().resolve();
  assert.equal(await saved, true);
});

test('Ctrl и Cmd добавляют объекты в выделение; толщина и удаление применяются ко всем', () => {
  for (const modifier of ['ctrlKey', 'metaKey']) {
    const {widget: w} = setup(); w.addPage(); w.tool = 'select';
    const page = w.page();
    const a = {id: 'a', t: 'line', c: '#000000', w: 2, p: [[10, 10], [50, 10]]};
    const b = {id: 'b', t: 'line', c: '#000000', w: 2, p: [[10, 80], [50, 80]]};
    w.commit(page, [a, b]);
    w.startSelect({pointerId: 1}, [25, 10]);
    w.startSelect({pointerId: 2, [modifier]: true}, [25, 80]);
    assert.deepEqual(Array.from(w.selection).sort(), ['a', 'b']);
    w.rewidthSelection(7);
    assert.ok(page.layers.student.elements.every(e => e.w === 7));
    w.undo();
    assert.ok(page.layers.student.elements.every(e => e.w === 2));
    w.startSelect({pointerId: 1}, [25, 10]);
    w.startSelect({pointerId: 2, [modifier]: true}, [25, 80]);
    w.rewidthSelection(4);
    w.moveSelection(10, 15);
    assert.equal(page.layers.student.elements[0].p[0][0], 20);
    assert.equal(page.layers.student.elements[1].p[0][1], 95);
    w.deleteSelection();
    assert.equal(page.layers.student.elements.length, 0);
    w.undo();
    assert.equal(page.layers.student.elements.length, 2);
  }
});

test('удаление пустой страницы ждёт сохранения и отправляет запрос на правильный адрес', async () => {
  const env = setup(), w = env.widget;
  w.addPage(); w.addPage();
  const previous = w.pages[0];
  previous.dirty = false; previous.layers.student.version = 1;
  const deleting = w.removeLastPage();
  assert.equal(env.calls[0].url, w.url + '2/');
  assert.equal(w.removing, true);
  env.pending.shift().resolve(); await drain();
  assert.equal(env.calls[1].url, w.url + '2/delete/');
  env.pending.shift().resolve(200, {ok: true});
  assert.equal(await deleting, true);
  assert.equal(w.pages.length, 1);
  assert.equal(w.removing, false);
});

test('очистка включает удаление последней страницы, а отмена снова выключает', () => {
  const {widget: w} = setup(); w.addPage();
  const page = w.page();
  // Подсказка ставится через data-tip и aria-label (setTip) — заглушке нужны эти поля
  w.deletePageButton = {dataset: {}, setAttribute() {}, removeAttribute() {}};
  w.commit(page, [stroke('a')]); w.syncDeleteButton();
  assert.equal(w.deletePageButton.disabled, true);
  w.clearPage(); w.syncDeleteButton();
  assert.equal(w.deletePageButton.disabled, false);
  w.undo(); w.syncDeleteButton();
  assert.equal(w.deletePageButton.disabled, true);
});

test('закрытие прячет доску, сохраняя рисунок и кнопку открытия', () => {
  const {widget: w} = setup(); w.addPage();
  w.launcher = {setAttribute(name, value) { this[name] = value; }};
  w.commit(w.page(), [stroke('a')]);
  w.flushAll = () => Promise.resolve(true);
  w.close();
  assert.equal(w.root.hidden, true);
  assert.equal(w.launcher.hidden, false);
  assert.equal(w.launcher['aria-expanded'], 'false');
  assert.equal(w.page().layers.student.elements[0].id, 'a');
});

test('новая страница квадратная, старая сохраняет систему координат', () => {
  const {widget: w} = setup(); w.addPage();
  assert.equal(w.page().bgOptions.square, true);
  assert.equal(w.makePage({number: 1}).bgOptions.square, undefined);
  w.stage = {clientWidth: 600, style: {}};
  w.base = {style: {}}; w.top = {style: {}};
  w.resize();
  assert.equal(w.base.width, w.base.height);
});

test('старая плоскость центрируется вместе с рисунком, указатель учитывает смещение', () => {
  const {widget: w} = setup();
  w.pages = [w.makePage({number: 1, background: 'plane', background_options: {cell: 50, origin: 'center'}})];
  w.index = 0; w.scale = 0.5;
  let transform;
  w.context({getContext() { return {setTransform(...args) { transform = args; }}; }});
  assert.equal(transform[5], 50);
  w.stage = {getBoundingClientRect() { return {left: 0, top: 0}; }};
  assert.deepEqual(Array.from(w.point({clientX: 250, clientY: 250})), [500, 400]);
});

test('merge подменяет чужой слой, синхронизирует права и убирает удалённые страницы', () => {
  const {widget: w} = setup();
  w.loaded = true; w.built = true; w.layer = null; w.canAddPages = false; w.showTeacherLayer = true; w.pending = []; w.selection = [];
  w.pages = [
    w.makePage({number: 1, locked: true, student: {elements: [stroke('a')], version: 1}, teacher: {elements: [], version: 0}}),
    w.makePage({number: 2, locked: true, student: {elements: [], version: 1}, teacher: {elements: [], version: 0}}),
  ];
  w.index = 1;
  let refreshed = 0; w.refresh = () => { refreshed++; }; w.updateNonEmpty = () => {};
  // Работу вернули: слой ученика снова открыт, страницу 2 удалили в другой вкладке, у страницы 1 — пометка
  const changed = w.merge({ok: true, layer: 'student', can_add_pages: true, show_teacher_layer: true, pages: [
    {number: 1, locked: true, background: 'grid', background_options: {}, created_by_role: 'student',
     student: {elements: [stroke('a')], version: 1}, teacher: {elements: [stroke('t')], version: 1}},
  ]});
  assert.equal(changed, true);
  assert.equal(w.layer, 'student');
  assert.equal(w.canAddPages, true);
  assert.equal(w.pages.length, 1);
  assert.equal(w.index, 0);
  assert.equal(w.pages[0].layers.teacher.elements[0].id, 't');
  assert.equal(w.pages[0].layers.student.elements[0].id, 'a');
  assert.equal(refreshed, 1);
  // Несохранённая заготовка и грязная страница не удаляются
  w.addPage();
  w.commit(w.page(), [stroke('b')]);
  const local = w.pages.length;
  assert.equal(w.merge({ok: true, layer: 'student', can_add_pages: true, show_teacher_layer: true, pages: [
    {number: 1, locked: true, background: 'grid', background_options: {}, created_by_role: 'student',
     student: {elements: [stroke('a')], version: 1}, teacher: {elements: [stroke('t')], version: 1}},
  ]}), false);
  assert.equal(w.pages.length, local);
});

test('рисунок: углы, попадание внутрь, масштаб с Shift, поворот на 90°, наклон', () => {
  const env = setup();
  const eq = (a, b) => assert.deepEqual(JSON.parse(JSON.stringify(a)), b);   /* массивы из vm-контекста */
  const geo = env.context.EgorCanvas.image;
  const el = {id: 'i', t: 'img', s: 1, w: 1, c: '#000', p: [[100, 100], [500, 100], [100, 400]]};
  eq(geo.corners(el)[2], [500, 400]);
  assert.equal(geo.inside(el, [300, 250]), true);
  assert.equal(geo.inside(el, [600, 250]), false);
  const hs = geo.handles(el);
  assert.equal(hs.length, 9);
  eq(hs[4].at, [300, 100]);
  eq(hs[8].at, [300, 60]);
  // правый нижний угол тянем к (900, 700): ширина ×2, высота ×2, левый верхний на месте
  let out = geo.transform(el, hs[2], [500, 400], [900, 700], false);
  eq(out.p, [[100, 100], [900, 100], [100, 700]]);
  // с Shift — пропорционально: (900, 400) даёт средний коэффициент 1.5
  out = geo.transform(el, hs[2], [500, 400], [900, 400], true);
  eq(out.p, [[100, 100], [700, 100], [100, 550]]);
  // поворот на 90° вокруг центра (300, 250): сохраняет длины сторон
  const c = [300, 250];
  out = geo.transform(el, hs[8], [300, 60], [490, 250], false);
  const d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  assert.equal(Math.round(d(out.p[0], out.p[1])), 400);
  assert.equal(Math.round(d(out.p[0], out.p[2])), 300);
  eq(out.p[0], [450, 50]);
  // с Shift — шаг 15°: почти 90° становится ровно 90°
  out = geo.transform(el, hs[8], [300, 60], [480, 240], true);
  eq(out.p[0], [450, 50]);
  // наклон: верхняя сторона сдвигается вдоль u на 50, нижняя стоит
  out = geo.transform(el, hs[4], [300, 100], [350, 130], false);
  eq(out.p, [[150, 100], [550, 100], [100, 400]]);
  eq(geo.corners(out)[2], [500, 400]);
});

test('картинки: ожидание привязано к URL, ошибка будит ожидающих, redraw не копит подписки', () => {
  const env = setup();
  const geo = env.context.EgorCanvas.image;
  const images = [];
  env.context.Image = function () { images.push(this); };
  const a = geo.of('/a.png'), b = geo.of('/b.png');
  const got = [];
  geo.settle('/a.png', e => got.push('a:' + (e.ready ? 'ok' : 'fail')));
  geo.settle('/b.png', e => got.push('b:' + (e.ready ? 'ok' : 'fail')));
  images[0].onload();                      // загрузилась только a
  assert.deepEqual(got, ['a:ok']);
  images[1].onerror();                     // b не смогла — её ожидающий тоже разбужен
  assert.deepEqual(got, ['a:ok', 'b:fail']);
  geo.settle('/a.png', e => got.push('late:' + e.ready));   // уже готова — сразу
  assert.deepEqual(got, ['a:ok', 'b:fail', 'late:true']);
  // redraw: подписка на неготовую картинку одна на URL, сколько бы раз ни рисовали
  const {widget: w} = env;
  w.addPage();
  w.page().layers.student.elements = [{id: 'i', t: 'img', s: 1, u: '/c.png', w: 1, c: '#000', p: [[0, 0], [10, 0], [0, 10]]}];
  env.context.requestAnimationFrame = () => 1;
  env.context.document.body = {contains: () => true};
  const redraw = env.context.EgorCanvas.Widget.prototype.redraw;   /* setup() глушит redraw заглушкой */
  redraw.call(w); redraw.call(w); redraw.call(w);
  const c = geo.of('/c.png');
  assert.equal(c.waiters.length, 1);
  assert.equal(geo.pending(w.page().layers.student.elements).length, 1);
  images[2].onload();
  assert.equal(c.waiters.length, 0);
  assert.equal(geo.pending(w.page().layers.student.elements).length, 0);
});

test('точка на осях без сетки — без подписи координат, на клетке — в узле с подписью', () => {
  const {widget: w} = setup(); w.addPage();
  Object.assign(w, {tool: 'dot', snap: true, scale: 1, color: '#000000', penWidth: 2, drawTop() {}, syncToolbar() {},
    stage: {getBoundingClientRect: () => ({left: 0, top: 0}), setPointerCapture() {}}});
  const down = () => w.onDown({button: 0, pointerType: 'mouse', pointerId: 1, clientX: 523, clientY: 481, preventDefault() {}});
  const page = w.page();
  page.background = 'plane';
  page.bgOptions = {square: true, cell: 50, origin: 'center', grid: false};
  down();
  let dot = page.layers.student.elements.at(-1);
  assert.equal(dot.l, false);
  assert.deepEqual([...dot.p[0]], [523, 481]);
  page.bgOptions = {square: true, cell: 50, origin: 'center'};
  down();
  dot = page.layers.student.elements.at(-1);
  assert.equal(dot.l, true);
  assert.deepEqual([...dot.p[0]], [500, 500]);
});

test('дублирование: копия больше лимита байт слоя не создаётся, обычная — создаётся', () => {
  const {widget: w} = setup(); w.addPage();
  const source = w.page();
  source.layers.student.elements = [stroke('a'), stroke('b')];
  w.limits = Object.assign({}, w.limits, {bytes: 50});
  w.duplicatePage();
  assert.equal(w.pages.length, 1);
  w.limits.bytes = 512 * 1024;
  w.duplicatePage();
  assert.equal(w.pages.length, 2);
  assert.equal(w.page().layers.student.elements.length, 2);
  assert.notEqual(w.page().layers.student.elements[0].id, 'a');
  assert.equal(source.layers.student.elements[0].id, 'a');
});
