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
    document, Promise, WeakMap, setTimeout() { return 1; }, clearTimeout() {},
    localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    addEventListener() {},
    fetch(url, options) {
      calls.push({url, body: JSON.parse(options.body)});
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
    root: {dataset: {}}, url: '/assignments/1/canvas/1/', role: 'student', layer: 'student',
    pages: [], limits: {student: 5, teacher: 2, total: 10, elements: 2000},
    refresh() {}, redraw() {}, syncHistoryButtons() {},
  });
  Widget.all.push(widget);
  return {widget, listeners, storage, calls, pending};
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
