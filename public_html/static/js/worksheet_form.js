/* «Свойства листка» (worksheets/worksheet_form.html): живая шапка PDF,
   сохранённые настройки листка (worksheets/presets.py) и подсказка имени
   PDF-файла по префиксу и названию — тем же правилом, что
   worksheets/filenames.py (translit, abbreviate, title_slug, clean_prefix). */
(function () {
  'use strict';

  var root = document.querySelector('[data-worksheet-props]');
  if (!root) return;

  var TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
  };
  var STOP_WORDS = ['и', 'в', 'во', 'на', 'с', 'со', 'к', 'ко', 'о', 'об', 'по',
    'для', 'от', 'до', 'из', 'а', 'у', 'за', 'при'];
  var VOWELS = 'аеёиоуыэюяьъ';
  var SLUG_WORDS = 3, ABBR_MIN = 4, ABBR_MAX = 6;

  function tr(text) {
    return Array.prototype.map.call(text.toLowerCase(), function (ch) {
      return Object.prototype.hasOwnProperty.call(TRANSLIT, ch) ? TRANSLIT[ch] : ch;
    }).join('');
  }

  function translit(text) {
    return tr(text).replace(/[^a-z0-9]+/g, '');
  }

  function abbreviate(word) {
    if (!/^[а-яё]+$/.test(word)) return translit(word).slice(0, ABBR_MAX);
    var cut = ABBR_MIN;
    while (cut < Math.min(word.length, ABBR_MAX) && VOWELS.indexOf(word[cut - 1]) !== -1) cut += 1;
    return translit(word.slice(0, cut));
  }

  function titleSlug(title) {
    var words = title.toLowerCase().match(/[а-яёa-z0-9]+/g) || [];
    return words.filter(function (w) { return STOP_WORDS.indexOf(w) === -1; })
      .map(abbreviate).filter(Boolean).slice(0, SLUG_WORDS).join('_');
  }

  function cleanPrefix(text) {
    return tr((text || '').trim()).replace(/\s+/g, '-').replace(/[^a-z0-9_-]+/g, '')
      .replace(/([_-])[_-]+/g, '$1').replace(/^[-_]+|[-_]+$/g, '');
  }

  var form = root;
  var field = function (name) { return form.elements.namedItem(name); };
  var nameBox = root.querySelector('[data-pdf-name]');

  function updateFilename() {
    if (!nameBox) return;
    var basename = (field('pdf_basename').value || '').trim();
    var prefix = cleanPrefix(field('pdf_prefix').value) || root.dataset.autoPrefix || 'math';
    var slug = titleSlug(field('title').value || '');
    nameBox.textContent = (basename || (slug ? prefix + '-' + slug : prefix)) + '.pdf';
  }

  ['title', 'pdf_prefix', 'pdf_basename'].forEach(function (name) {
    var input = field(name);
    if (input) input.addEventListener('input', updateFilename);
  });
  updateFilename();

  /* Сохранённые настройки: выбор подставляет шапку и префикс без запроса */
  var dataNode = document.getElementById('worksheet-presets');
  var presets = dataNode ? JSON.parse(dataNode.textContent) : [];
  var select = root.querySelector('[data-preset-select]');
  var deleteBtn = root.querySelector('[data-preset-delete]');
  var dialog = document.getElementById('preset-dialog');
  var dialogForm = dialog && dialog.querySelector('[data-preset-form]');
  var FIELDS = ['grade_label', 'author_name', 'subtitle', 'pdf_prefix'];

  function csrf() {
    var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  function toast(ok, message) {
    if (window.EgorAutosave) window.EgorAutosave.showSaved(ok, message);
  }

  function presetById(id) {
    return presets.filter(function (p) { return String(p.id) === String(id); })[0];
  }

  function syncDeleteButton() {
    if (deleteBtn) deleteBtn.hidden = !select.value;
  }

  function optionLabel(preset) {
    return preset.name + (preset.is_default ? ' (для новых)' : '');
  }

  if (select) {
    select.addEventListener('change', function () {
      var preset = presetById(select.value);
      syncDeleteButton();
      if (!preset) return;
      FIELDS.forEach(function (name) {
        var input = field(name);
        if (input) input.value = preset.values[name] || '';
      });
      updateFilename();
      if (dialogForm) dialogForm.elements.namedItem('name').value = preset.name;
    });
  }

  if (deleteBtn) {
    deleteBtn.addEventListener('click', function () {
      var preset = presetById(select.value);
      if (!preset || !confirm('Удалить настройки «' + preset.name + '»? Листки не изменятся.')) return;
      var url = root.dataset.presetDeleteUrl.replace(/\/0\/delete\/$/, '/' + preset.id + '/delete/');
      fetch(url, {method: 'POST', headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest'}})
        .then(function (r) { return r.json(); })
        .then(function (data) {
          toast(data.ok, data.message);
          if (!data.ok) return;
          presets = presets.filter(function (p) { return p.id !== preset.id; });
          var option = select.querySelector('option[value="' + preset.id + '"]');
          if (option) option.remove();
          select.value = '';
          syncDeleteButton();
        })
        .catch(function () { toast(false, 'Нет связи — настройки не удалены'); });
    });
  }

  if (dialogForm) {
    dialogForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var body = new FormData();
      body.append('name', dialogForm.elements.namedItem('name').value);
      if (dialogForm.elements.namedItem('is_default').checked) body.append('is_default', '1');
      FIELDS.forEach(function (name) { body.append(name, field(name) ? field(name).value : ''); });
      fetch(root.dataset.presetSaveUrl, {
        method: 'POST', body: body,
        headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest'}
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          toast(data.ok, data.message);
          if (!data.ok) return;
          var saved = data.preset;
          if (saved.is_default) presets.forEach(function (p) { p.is_default = false; });
          presets = presets.filter(function (p) { return p.id !== saved.id; }).concat([saved]);
          Array.prototype.forEach.call(select.options, function (option) {
            var p = presetById(option.value);
            if (p) option.textContent = optionLabel(p);
          });
          var option = select.querySelector('option[value="' + saved.id + '"]');
          if (!option) {
            option = document.createElement('option');
            option.value = saved.id;
            select.appendChild(option);
          }
          option.textContent = optionLabel(saved);
          if (select.options[0] && !select.options[0].value) select.options[0].textContent = 'не выбраны';
          select.value = String(saved.id);
          syncDeleteButton();
          // «Сохранить» во всплывающем окне после успеха закрывает окно
          dialog.close();
        })
        .catch(function () { toast(false, 'Нет связи — настройки не сохранены'); });
    });
  }
})();
