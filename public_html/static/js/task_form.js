/* Форма задачи: динамические строки формсетов, «замки» закрепления
   параметров, вставка картинок из буфера обмена, нумерация \taskpic. */
(function () {
  'use strict';

  var PINS_KEY = 'egormath-task-pins';
  var VALUES_KEY = 'egormath-task-pin-values';

  function readJSON(key) {
    try { return JSON.parse(localStorage.getItem(key)) || {}; }
    catch (e) { return {}; }
  }
  function writeJSON(key, obj) {
    try { localStorage.setItem(key, JSON.stringify(obj)); } catch (e) {}
  }

  function init() {
    var root = document.getElementById('task-form');
    if (!root) return;
    var forms = root.matches('form') ? [root] : root.querySelectorAll('[data-editor-form]');
    forms.forEach(initForm);
  }

  function initForm(form) {
    if (form.dataset.formReady) return;
    form.dataset.formReady = '1';
    var imagesTable = form.querySelector('table[data-images]');

    // --- Динамические строки формсетов ---
    // Удалённая строка не выкидывается из POST, а очищается до значений
    // по умолчанию: такую «пустую» форму Django игнорирует при сохранении.
    function resetRow(row) {
      row.querySelectorAll('input, textarea, select').forEach(function (el) {
        if (el.type === 'file') { el.value = ''; }
        else if (el.type === 'checkbox' || el.type === 'radio') {
          el.checked = el.defaultChecked;
        } else if (el.tagName === 'SELECT') {
          Array.prototype.forEach.call(el.options, function (o) {
            o.selected = o.defaultSelected;
          });
        } else { el.value = el.defaultValue; }
      });
    }

    function renumberPics() {
      if (!imagesTable) return;
      var n = 0;
      imagesTable.querySelectorAll('tr.formset-row').forEach(function (row) {
        if (row.hidden) return;
        n += 1;
        var cell = row.querySelector('.pic-snippet');
        if (cell) cell.textContent = '\\taskpic{' + n + '}';
      });
    }

    form.querySelectorAll('.formset-add').forEach(function (btn) {
      var prefix = btn.dataset.formset;
      var table = form.querySelector('table[data-formset="' + prefix + '"]');
      var tmpl = form.querySelector('template[data-formset="' + prefix + '"]');
      var total = document.getElementById('id_' + prefix + '-TOTAL_FORMS');
      btn.addEventListener('click', function () {
        var html = tmpl.innerHTML.replace(/__prefix__/g, total.value);
        total.value = String(Number(total.value) + 1);
        table.tBodies[0].insertAdjacentHTML('beforeend', html);
        renumberPics();
        btn.dispatchEvent(new Event('change', {bubbles: true}));
      });
    });

    form.addEventListener('click', function (e) {
      var btn = e.target.closest('.formset-remove');
      if (!btn) return;
      var row = btn.closest('tr');
      resetRow(row);
      row.hidden = true;
      btn.dispatchEvent(new Event('change', {bubbles: true}));
      renumberPics();
    });

    // --- Превью картинок (в т.ч. только что выбранных или вставленных) ---
    form.addEventListener('change', function (e) {
      var input = e.target;
      if (input.type !== 'file' || !imagesTable
          || !imagesTable.contains(input)) return;
      var img = input.closest('tr').querySelector('.pic-preview');
      var file = input.files && input.files[0];
      // Превью только для растровых файлов (PDF браузер в <img> не покажет)
      if (img && file && file.type.indexOf('image/') === 0) {
        img.src = URL.createObjectURL(file);
        img.hidden = false;
      }
    });

    // --- Вставка картинки из буфера обмена ---
    function firstEmptyFileInput() {
      if (!imagesTable) return null;
      var inputs = imagesTable.querySelectorAll(
        'tr.formset-row:not([hidden]) input[type=file]');
      for (var i = 0; i < inputs.length; i += 1) {
        if (!inputs[i].files.length) return inputs[i];
      }
      return null;
    }

    document.addEventListener('paste', function (e) {
      if (!form.isConnected) return;
      var files = e.clipboardData ? e.clipboardData.files : null;
      if (!files || !files.length
          || files[0].type.indexOf('image/') !== 0) return;
      var input = firstEmptyFileInput();
      if (!input) {
        var addBtn = imagesTable && form.querySelector(
          '.formset-add[data-formset="' + imagesTable.dataset.formset + '"]');
        if (!addBtn) return;
        addBtn.click();
        input = firstEmptyFileInput();
      }
      if (!input) return;
      var dt = new DataTransfer();
      dt.items.add(files[0]);
      input.files = dt.files;
      input.dispatchEvent(new Event('change', {bubbles: true}));
      e.preventDefault();
    });

    renumberPics();

    // --- «Замки»: закрепить параметры для следующих новых задач ---
    function fieldControls(name) {
      return form.querySelectorAll('[name="' + name + '"]');
    }

    function getValue(name) {
      if (window.EgorTaxonomy && window.EgorTaxonomy.has(form, name)) {
        return window.EgorTaxonomy.get(form, name);
      }
      var els = fieldControls(name);
      if (!els.length) return null;
      var el = els[0];
      if (el.tagName === 'SELECT' && el.multiple) {
        return Array.prototype.filter.call(el.options, function (o) {
          return o.selected;
        }).map(function (o) { return o.value; });
      }
      if (el.type === 'checkbox') {
        return Array.prototype.filter.call(els, function (c) {
          return c.checked;
        }).map(function (c) { return c.value; });
      }
      return el.value;
    }

    function setValue(name, value) {
      if (window.EgorTaxonomy && window.EgorTaxonomy.set(form, name, value)) {
        return;
      }
      var els = fieldControls(name);
      if (!els.length || value == null) return;
      var el = els[0];
      if (el.tagName === 'SELECT' && el.multiple) {
        Array.prototype.forEach.call(el.options, function (o) {
          o.selected = value.indexOf(o.value) !== -1;
        });
      } else if (el.type === 'checkbox') {
        Array.prototype.forEach.call(els, function (c) {
          c.checked = value.indexOf(c.value) !== -1;
        });
      } else { el.value = value; }
    }

    var pins = readJSON(PINS_KEY);
    var pinInputs = form.querySelectorAll('.pin-toggle input[data-pin]');

    function paintPin(input) {
      var icon = input.parentElement.querySelector('.pin-icon');
      if (icon) icon.textContent = input.checked ? '🔒' : '🔓';
    }

    pinInputs.forEach(function (input) {
      var name = input.dataset.pin;
      input.checked = !!pins[name];
      paintPin(input);
      input.addEventListener('change', function () {
        pins[name] = input.checked;
        writeJSON(PINS_KEY, pins);
        var values = readJSON(VALUES_KEY);
        if (input.checked) values[name] = getValue(name);
        else delete values[name];
        writeJSON(VALUES_KEY, values);
        paintPin(input);
      });
    });

    // Форма новой задачи: применяем закреплённые значения
    if (form.dataset.newTask) {
      var stored = readJSON(VALUES_KEY);
      pinInputs.forEach(function (input) {
        var name = input.dataset.pin;
        if (input.checked && name in stored) setValue(name, stored[name]);
      });
    }

    // Значения закреплённых полей запоминаем при изменении и при сохранении
    function storePinnedValues() {
      var values = readJSON(VALUES_KEY);
      pinInputs.forEach(function (input) {
        if (input.checked) values[input.dataset.pin] = getValue(input.dataset.pin);
      });
      writeJSON(VALUES_KEY, values);
    }
    form.addEventListener('change', function (e) {
      if (e.target.name) storePinnedValues();
    });
    form.addEventListener('submit', storePinnedValues);
  }
  window.EgorTaskForm = {init: init};
  document.addEventListener('DOMContentLoaded', init);
})();
