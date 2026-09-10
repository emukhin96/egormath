/* Медленное автосохранение не должно перезаписывать проверенный ответ. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('автосохранение, проверка и новый ввод выполняются в порядке отправки', async () => {
  const ready = [], calls = [], pending = [];
  let click;
  const form = {value:'старый', action:'/save', addEventListener(){}, dispatchEvent(){}, querySelector(){return {value:'csrf'};}};
  const button = {form, getAttribute(){return '/check';}, addEventListener(_, cb){click=cb;}};
  class FormData {
    constructor(f){this.value=f.value;}
    forEach(cb){cb(this.value,'answer');}
  }
  const document = {
    addEventListener(name, cb){if(name==='DOMContentLoaded')ready.push(cb);},
    getElementById(id){return id==='answers-form'?form:null;},
    querySelectorAll(selector){return selector==='[data-check-task]'?[button]:[];},
    querySelector(){return null;},
  };
  const context={document, FormData, Promise, WeakMap, setTimeout, clearTimeout, CustomEvent:class {},
    fetch(url, options){calls.push([url,options.body.value]);return new Promise(resolve=>pending.push(()=>resolve({ok:true,json:async()=>({ok:true})})));}};
  context.window=context;
  vm.createContext(context);
  for(const name of ['autosave','assignment'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../public_html/static/js',name+'.js'),'utf8'),context);
  ready.forEach(cb=>cb());
  const drain=()=>new Promise(resolve=>setImmediate(resolve));
  const first=context.EgorAutosave.autosave(form);
  await drain();
  form.value='верный';click({preventDefault(){}});
  form.value='новый';const last=context.EgorAutosave.autosave(form);
  assert.deepEqual(calls,[['/save','старый']]);
  pending.shift()();await first;await drain();
  assert.deepEqual(calls,[['/save','старый'],['/check','верный']]);
  pending.shift()();await drain();
  assert.deepEqual(calls,[['/save','старый'],['/check','верный'],['/save','новый']]);
  pending.shift()();await last;
  assert.equal(button.disabled,false);
});
