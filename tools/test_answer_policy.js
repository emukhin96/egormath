/* Регрессия: блокировка переключателя не должна терять его значение. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function setup(checked, outcome) {
  const handlers = {}, sent = [], messages = [];
  const root = {};
  const policyForm = {closest: () => ({querySelector: () => root})};
  const toggle = {checked, disabled: false, form: policyForm};
  const control = {addEventListener() {}};
  const maskForm = {
    elements: {source: control},
    querySelector: () => control,
    querySelectorAll: () => [],
    addEventListener() {},
  };
  const document = {
    getElementById(id) {
      if (id === 'toggle-masks') return null;
      if (id === 'answer-mask-form') return maskForm;
      return {dataset: {}};
    },
    addEventListener(event, handler) {handlers[event] = handler;},
  };
  class FormData {
    constructor(form) {
      assert.equal(form, policyForm);
      this.values = new Map();
      // Семантика браузера: disabled и unchecked checkbox не отправляются.
      if (!toggle.disabled && toggle.checked) this.values.set('full_answer_only', 'on');
    }
    get(key) {return this.values.get(key) || null;}
  }
  const context = {document, FormData, window: {EgorProblem: {
    async save(source, data, form) {
      assert.equal(source, root);
      assert.equal(form, policyForm);
      assert.equal(toggle.disabled, true);
      sent.push(data.get('full_answer_only'));
      if (outcome instanceof Error) throw outcome;
      return outcome;
    },
    toast(ok, message) {messages.push([ok, message]);},
  }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,
    '../public_html/static/js/problem_masks.js'), 'utf8'), context);
  return {toggle, sent, messages, change: () => handlers.change({target: {closest: () => toggle}})};
}

for (const checked of [true, false]) {
  test('сохраняется значение переключателя: ' + checked, async () => {
    const ui = setup(checked, {ok: true});
    await ui.change();
    assert.deepEqual(ui.sent, [checked ? 'on' : null]);
    assert.equal(ui.toggle.checked, checked);
    assert.equal(ui.toggle.disabled, false);
  });
  test('отмена возвращает предыдущее значение: ' + checked, async () => {
    const ui = setup(checked, null);
    await ui.change();
    assert.equal(ui.toggle.checked, !checked);
    assert.equal(ui.toggle.disabled, false);
  });
  test('ошибка возвращает значение и разблокирует переключатель: ' + checked, async () => {
    const ui = setup(checked, new Error('Нет связи'));
    await ui.change();
    assert.equal(ui.toggle.checked, !checked);
    assert.equal(ui.toggle.disabled, false);
    assert.deepEqual(ui.messages, [[false, 'Нет связи']]);
  });
}

test('сохранение обновляет строки копии и повторов, не перезагружая документ', async () => {
  const replaced = [], events = [], calls = [];
  const fresh = {dataset: {taskId: '20'}, querySelectorAll: () => []};
  const rows = ['10', '30'].map((taskId, i) => ({dataset: {taskId, id: String(i)},
    replaceWith() {replaced.push(i);}}));
  const parsed = {querySelector(selector) {
    if (selector === '#ws-items') return {};
    return selector.includes('"0"') ? fresh : {dataset: {taskId: '30'}};
  }};
  const document = {
    addEventListener() {},
    querySelector: () => ({value: 'csrf'}),
    querySelectorAll: () => rows,
    dispatchEvent(e) {events.push(e.type);},
  };
  const root = {dataset: {taskId: '10', manageUrl: '/problems/10/manage/'},
    matches: selector => selector === '[data-worksheet-mask]', closest: () => ({})};
  const context = {document, URL, CustomEvent: class {constructor(type) {this.type = type;}},
    DOMParser: class {parseFromString() {return parsed;}},
    location: {href: 'http://localhost/worksheets/1/', reload() {assert.fail('Перезагрузка запрещена');}},
    renderMathContent() {},
    window: {EgorAutosave: {showSaved() {}}},
    async fetch(url, options) {
      calls.push({url: String(url), method: options.method});
      return {ok: true, json: async () => ({ok: true, task_id: 20}), text: async () => '<html></html>'};
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,
    '../public_html/static/js/problem_editor.js'), 'utf8'), context);
  const result = await context.window.EgorProblem.save(root, new Map());
  assert.equal(result.ok, true);
  assert.deepEqual(replaced, [0]);
  assert.deepEqual(events, ['worksheet:updated']);
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[1].url, 'http://localhost/worksheets/1/');
});
