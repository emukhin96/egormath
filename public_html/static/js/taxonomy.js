/* Виджет рубрикатора: поиск по коду/названию, дерево, чипы, фасеты.
   Каталог один на страницу (#taxonomy-catalog). В компактном режиме
   клик открывает дерево (ветка раскрывается, лист выбирается), набор
   текста сужает список листьев. Скрытые input'ы пишутся в ту же форму. */
(function () {
  'use strict';

  var catalog = null;
  var pickers = [];
  var loading = null;

  // Каталог либо встроен в страницу (<script id="taxonomy-catalog">…JSON…),
  // либо лежит по data-src и грузится один раз отдельным запросом —
  // браузер кэширует его между страницами.
  function loadCatalog() {
    if (catalog) return catalog;
    var el = document.getElementById('taxonomy-catalog');
    if (!el || !el.textContent.trim()) return null;
    try { catalog = JSON.parse(el.textContent); }
    catch (e) { catalog = null; }
    return catalog;
  }

  function fetchCatalog() {
    var el = document.getElementById('taxonomy-catalog');
    var src = el && el.getAttribute('data-src');
    if (!src) return Promise.resolve(null);
    if (!loading) {
      // Неуспешный ответ (502/503 при деплое и т. п.) — такая же ошибка,
      // как обрыв сети: loading сбрасывается, следующий init() запросит
      // каталог заново.
      loading = fetch(src, {credentials: 'same-origin'})
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (data) {
          if (!data || !data.topics) throw new Error('bad catalog');
          catalog = data;
          return data;
        })
        .catch(function () { loading = null; return null; });
    }
    return loading;
  }

  // Готовность рубрикатора: промис разрешается, когда каталог получен и
  // виджеты созданы. Форма задачи ждёт его, прежде чем восстанавливать
  // закреплённые темы/классы/метки — до этого EgorTaxonomy.set() некуда
  // писать.
  var readyResolve = null;
  var readyPromise = new Promise(function (resolve) { readyResolve = resolve; });

  function showLoadError() {
    document.querySelectorAll('[data-tax-picker]').forEach(function (el) {
      if (el.dataset.taxReady || el.querySelector('[data-tax-error]')) return;
      var box = document.createElement('p');
      box.className = 'tax-empty';
      box.setAttribute('data-tax-error', '');
      box.setAttribute('role', 'alert');
      box.textContent = 'Не удалось загрузить рубрикатор. ';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-secondary btn-small';
      btn.textContent = 'Повторить';
      btn.addEventListener('click', function () {
        btn.disabled = true;
        init();
      });
      box.appendChild(btn);
      el.insertBefore(box, el.firstChild);
    });
  }

  function clearLoadError() {
    document.querySelectorAll('[data-tax-picker] [data-tax-error]')
      .forEach(function (box) { box.remove(); });
  }

  function parseState(raw) {
    if (!raw) {
      return {topics: [], primary: null, grades: [], facets: [], exams: [],
              difficulty: null};
    }
    if (typeof raw === 'object') return raw;
    try { return JSON.parse(raw); }
    catch (e) {
      return {topics: [], primary: null, grades: [], facets: [], exams: [],
              difficulty: null};
    }
  }

  function topicById(id) {
    var topics = catalog && catalog.topics || [];
    for (var i = 0; i < topics.length; i += 1) {
      if (topics[i].id === id) return topics[i];
    }
    return null;
  }

  function matchesQuery(topic, q) {
    if (!q) return true;
    var hay = (topic.code + ' ' + topic.name).toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function isExamLine(item) {
    if (!item) return false;
    if (item.line) return true;
    return item.item_number === 0;
  }

  function examModelForItemId(id) {
    var exams = catalog && catalog.exams || [];
    var i;
    var j;
    for (i = 0; i < exams.length; i += 1) {
      var items = exams[i].items || [];
      for (j = 0; j < items.length; j += 1) {
        if (items[j].id === id) return exams[i];
      }
    }
    return null;
  }

  function examLineItem(model) {
    var items = model && model.items || [];
    var i;
    for (i = 0; i < items.length; i += 1) {
      if (isExamLine(items[i])) return items[i];
    }
    return null;
  }

  function ensureExamParentIds(ids) {
    var result = (ids || []).slice();
    var have = {};
    result.forEach(function (id) { have[id] = true; });
    result.slice().forEach(function (id) {
      var model = examModelForItemId(id);
      if (!model) return;
      var item = null;
      model.items.forEach(function (it) {
        if (it.id === id) item = it;
      });
      if (item && !isExamLine(item)) {
        var line = examLineItem(model);
        if (line && !have[line.id]) {
          result.push(line.id);
          have[line.id] = true;
        }
      }
    });
    return result;
  }

  function matchingIds(q) {
    var ids = {};
    if (!catalog) return ids;
    catalog.topics.forEach(function (topic) {
      if (matchesQuery(topic, q)) {
        ids[topic.id] = true;
        var parent = topic.parent;
        while (parent) {
          ids[parent] = true;
          var p = topicById(parent);
          parent = p ? p.parent : null;
        }
      }
    });
    return ids;
  }

  function ensureHidden(form, name, multiple) {
    var existing = form.querySelectorAll('[name="' + name + '"]');
    if (existing.length) return;
    if (multiple) {
      var sel = document.createElement('select');
      sel.name = name;
      sel.multiple = true;
      sel.hidden = true;
      sel.setAttribute('aria-hidden', 'true');
      form.appendChild(sel);
    } else {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      form.appendChild(input);
    }
  }

  function setSelectValues(form, name, values) {
    var sel = form.querySelector('select[name="' + name + '"]');
    if (!sel) return;
    sel.innerHTML = '';
    values.forEach(function (v) {
      var opt = document.createElement('option');
      opt.value = String(v);
      opt.selected = true;
      sel.appendChild(opt);
    });
  }

  function setHiddenValue(form, name, value) {
    var input = form.querySelector('input[name="' + name + '"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      form.appendChild(input);
    }
    input.value = value == null ? '' : String(value);
  }

  function Picker(root) {
    this.root = root;
    this.form = root.closest('form');
    this.mode = root.dataset.mode || 'assign';
    this.usePrimary = root.dataset.primary === '1';
    this.useFacets = root.dataset.facets === '1';
    this.useGrades = root.dataset.grades === '1';
    this.compact = root.dataset.compact === '1';
    this.single = root.dataset.single === '1';
    this.chipFull = root.dataset.chipFull === '1';
    this.topicFieldName = root.dataset.topicField || '';
    this.isFilter = this.mode === 'filter';
    this.state = parseState(root.dataset.state);
    if (!this.isFilter) {
      this.state.exams = ensureExamParentIds(this.state.exams || []);
    }
    this.query = '';
    this.open = {};
    this.facetsOpen = this.hasExtraSelection();
    this.chips = root.querySelector('[data-tax-chips]');
    this.search = root.querySelector('[data-tax-search]');
    this.panel = root.querySelector('[data-tax-panel]');
    this.tree = root.querySelector('[data-tax-tree]');
    this.gradesEl = root.querySelector('[data-tax-grades]');
    this.facets = root.querySelector('[data-tax-facets]');
    this.moreBtn = root.querySelector('[data-tax-more]');
    this.bind();
    this.syncHidden();
    this.render();
  }

  Picker.prototype.topicField = function () {
    return this.topicFieldName || (this.isFilter ? 'topic' : 'topics');
  };

  Picker.prototype.gradeField = function () {
    return this.isFilter ? 'grade' : 'grade_bands';
  };

  Picker.prototype.bind = function () {
    var self = this;
    if (this.search) {
      this.search.addEventListener('input', function () {
        self.query = self.search.value.trim().toLowerCase();
        if (self.compact) self.showPanel();
        else self.renderTree();
      });
      this.search.addEventListener('focus', function () {
        self.showPanel();
      });
      /* После выбора поле остаётся в фокусе — повторный клик иначе
         не даёт focus и панель не открывается. */
      this.search.addEventListener('click', function () {
        self.showPanel();
      });
      this.search.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          self.search.blur();
          self.hidePanel();
          return;
        }
        if (e.key !== 'Enter') return;
        e.preventDefault();
        var first = self.firstVisibleMatch();
        if (!first) return;
        self.toggleTopic(first, false);
        self.clearSearch();
        self.hidePanel();
      });
    }
    if (this.tree) {
      this.tree.addEventListener('mousedown', function (e) {
        if (e.target.closest('[data-tax-node], [data-tax-twist]')) {
          e.preventDefault();
        }
      });
    }
    this.root.addEventListener('click', function (e) {
      var star = e.target.closest('[data-tax-star]');
      if (star) {
        e.preventDefault();
        self.setPrimary(Number(star.dataset.taxStar));
        return;
      }
      var remove = e.target.closest('[data-tax-remove]');
      if (remove) {
        e.preventDefault();
        self.toggleTopic(Number(remove.dataset.taxRemove), true);
        return;
      }
      var twist = e.target.closest('[data-tax-twist]');
      if (twist) {
        e.preventDefault();
        self.toggleOpen(Number(twist.dataset.taxTwist));
        return;
      }
      var node = e.target.closest('[data-tax-node]');
      if (node) {
        e.preventDefault();
        self.onNode(Number(node.dataset.taxNode));
        return;
      }
      var grade = e.target.closest('[data-tax-grade]');
      if (grade) {
        e.preventDefault();
        self.toggleList('grades', grade.dataset.taxGrade);
        return;
      }
      var facet = e.target.closest('[data-tax-facet]');
      if (facet) {
        e.preventDefault();
        self.toggleList('facets', Number(facet.dataset.taxFacet));
        return;
      }
      var exam = e.target.closest('[data-tax-exam]');
      if (exam) {
        e.preventDefault();
        self.toggleExam(Number(exam.dataset.taxExam));
        return;
      }
      var more = e.target.closest('[data-tax-more]');
      if (more) {
        e.preventDefault();
        self.facetsOpen = !self.facetsOpen;
        self.syncExtra();
        return;
      }
      var diff = e.target.closest('[data-tax-diff]');
      if (diff) {
        e.preventDefault();
        var val = diff.dataset.taxDiff;
        self.state.difficulty = val ? Number(val) : null;
        self.afterChange();
      }
    });
    if (this.compact) {
      this.root.addEventListener('click', function (e) {
        if (e.target.closest('[data-tax-remove], [data-tax-star], [data-tax-node], [data-tax-twist]')) {
          return;
        }
        self.showPanel();
      });
    }
    document.addEventListener('mousedown', function (e) {
      if (!self.compact || !self.panel || self.panel.hidden) return;
      if (self.root.contains(e.target)) return;
      self.panel.hidden = true;
    });
  };

  Picker.prototype.clearSearch = function () {
    this.query = '';
    if (this.search) this.search.value = '';
    this.renderPanel();
  };

  Picker.prototype.showPanel = function () {
    if (!this.compact || !this.panel) return;
    pickers.forEach(function (other) {
      if (other !== this) other.hidePanel();
    }, this);
    this.panel.hidden = false;
    this.renderPanel();
  };

  Picker.prototype.hidePanel = function () {
    if (this.compact && this.panel) this.panel.hidden = true;
  };

  Picker.prototype.toggleOpen = function (id) {
    this.open[id] = !this.open[id];
    this.renderTree();
  };

  Picker.prototype.renderPanel = function () {
    if (this.compact && this.query) this.renderSuggest();
    else this.renderTree();
  };

  Picker.prototype.onNode = function (id) {
    var topic = topicById(id);
    if (!topic) return;
    if (!topic.leaf) {
      if (this.isFilter) {
        this.toggleTopic(id, false);
        if (this.compact) {
          this.clearSearch();
          this.hidePanel();
        }
        return;
      }
      this.toggleOpen(id);
      return;
    }
    this.toggleTopic(id, false);
    if (this.compact) {
      this.clearSearch();
      this.hidePanel();
    }
  };

  Picker.prototype.toggleTopic = function (id, forceOff) {
    var idx = this.state.topics.indexOf(id);
    if (this.single) {
      this.state.topics = (idx !== -1 || forceOff) ? [] : [id];
      this.state.primary = this.state.topics[0] || null;
      this.afterChange();
      return;
    }
    if (idx !== -1) {
      this.state.topics.splice(idx, 1);
      if (this.state.primary === id) {
        this.state.primary = this.state.topics[0] || null;
      }
    } else if (!forceOff) {
      this.state.topics.push(id);
      if (this.usePrimary && !this.state.primary) this.state.primary = id;
    }
    this.afterChange();
  };

  Picker.prototype.setPrimary = function (id) {
    if (this.state.topics.indexOf(id) === -1) this.state.topics.unshift(id);
    this.state.primary = this.state.primary === id ? null : id;
    this.afterChange();
  };

  Picker.prototype.toggleList = function (key, value) {
    var list = this.state[key] || [];
    var idx = list.indexOf(value);
    if (idx === -1) list.push(value);
    else list.splice(idx, 1);
    this.state[key] = list;
    this.afterChange();
  };

  Picker.prototype.toggleExam = function (id) {
    var list = (this.state.exams || []).slice();
    if (this.isFilter) {
      var filterIdx = list.indexOf(id);
      if (filterIdx === -1) list.push(id);
      else list.splice(filterIdx, 1);
      this.state.exams = list;
      this.afterChange();
      return;
    }
    var model = examModelForItemId(id);
    var line = examLineItem(model);
    var item = null;
    if (model) {
      model.items.forEach(function (it) {
        if (it.id === id) item = it;
      });
    }
    var idx = list.indexOf(id);
    var turningOn = idx === -1;
    if (item && isExamLine(item)) {
      if (turningOn) {
        list.push(id);
      } else if (model) {
        var drop = {};
        model.items.forEach(function (it) { drop[it.id] = true; });
        list = list.filter(function (x) { return !drop[x]; });
      } else {
        list.splice(idx, 1);
      }
    } else if (turningOn) {
      list.push(id);
      if (line && list.indexOf(line.id) === -1) list.push(line.id);
    } else {
      list.splice(idx, 1);
    }
    this.state.exams = list;
    this.afterChange();
  };

  Picker.prototype.afterChange = function () {
    this.syncHidden();
    this.render();
    this.notifyForm();
  };

  Picker.prototype.notifyForm = function () {
    if (!this.form) return;
    if (this.isFilter) {
      this.form.requestSubmit();
      return;
    }
    var sel = this.form.querySelector('select[name="' + this.topicField() + '"]');
    if (sel) {
      sel.dispatchEvent(new Event('change', {bubbles: true}));
    } else if (window.EgorAutosave && this.form.dataset.autosave === 'change') {
      window.EgorAutosave.autosave(this.form);
    }
  };

  Picker.prototype.syncHidden = function () {
    if (!this.form) return;
    if (!this.isFilter) {
      ensureHidden(this.form, 'topics_submitted', false);
      setHiddenValue(this.form, 'topics_submitted', '1');
    }
    ensureHidden(this.form, this.topicField(), !this.single);
    if (this.single) {
      setHiddenValue(
        this.form, this.topicField(), this.state.topics[0] || '');
    } else {
      setSelectValues(this.form, this.topicField(), this.state.topics);
    }
    if (this.usePrimary && !this.isFilter) {
      setHiddenValue(this.form, 'primary_topic', this.state.primary);
    }
    if (this.useGrades) {
      if (!this.isFilter) {
        ensureHidden(this.form, 'grades_submitted', false);
        setHiddenValue(this.form, 'grades_submitted', '1');
      }
      ensureHidden(this.form, this.gradeField(), true);
      setSelectValues(this.form, this.gradeField(), this.state.grades);
    }
    if (this.useFacets) {
      if (!this.isFilter) {
        ensureHidden(this.form, 'facets_submitted', false);
        setHiddenValue(this.form, 'facets_submitted', '1');
        ensureHidden(this.form, 'exams_submitted', false);
        setHiddenValue(this.form, 'exams_submitted', '1');
      }
      ensureHidden(this.form, this.isFilter ? 'level' : 'facet_values', true);
      if (this.isFilter) {
        var levelCodes = [];
        var methods = [];
        var levels = catalog && catalog.levels || [];
        (this.state.facets || []).forEach(function (id) {
          var found = levels.filter(function (x) { return x.id === id; })[0];
          if (found) levelCodes.push(found.code);
          else methods.push(id);
        });
        setSelectValues(this.form, 'level', levelCodes);
        ensureHidden(this.form, 'method', true);
        setSelectValues(this.form, 'method', methods);
        ensureHidden(this.form, 'exam', true);
        var examCodes = [];
        (catalog && catalog.exams || []).forEach(function (model) {
          model.items.forEach(function (item) {
            if (this.state.exams.indexOf(item.id) !== -1) examCodes.push(item.code);
          }, this);
        }, this);
        setSelectValues(this.form, 'exam', examCodes);
      } else {
        setSelectValues(this.form, 'facet_values', this.state.facets);
        ensureHidden(this.form, 'exam_items', true);
        setSelectValues(this.form, 'exam_items', this.state.exams);
        setHiddenValue(this.form, 'difficulty', this.state.difficulty);
      }
    }
  };

  Picker.prototype.hasExtraSelection = function () {
    return !!(this.state.facets && this.state.facets.length)
      || !!(this.state.exams && this.state.exams.length)
      || this.state.difficulty != null;
  };

  Picker.prototype.firstVisibleMatch = function () {
    if (!catalog) return null;
    var q = this.query;
    if (this.compact) {
      if (!q) return null;
      for (var i = 0; i < catalog.topics.length; i += 1) {
        var topic = catalog.topics[i];
        if (!this.isFilter && !topic.leaf) continue;
        if (matchesQuery(topic, q)) return topic.id;
      }
      return null;
    }
    var visible = matchingIds(q);
    var fallback = null;
    for (var j = 0; j < catalog.topics.length; j += 1) {
      var node = catalog.topics[j];
      if (q && !visible[node.id]) continue;
      if (!q && node.parent && !this.open[node.parent]) continue;
      if (node.leaf) return node.id;
      if (!fallback) fallback = node;
    }
    if (!fallback) return null;
    for (var k = 0; k < catalog.topics.length; k += 1) {
      var leaf = catalog.topics[k];
      if (!leaf.leaf) continue;
      var parent = leaf.parent;
      while (parent) {
        if (parent === fallback.id) return leaf.id;
        var up = topicById(parent);
        parent = up ? up.parent : null;
      }
    }
    return null;
  };

  Picker.prototype.renderSuggest = function () {
    if (!this.tree || !catalog) return;
    var q = this.query;
    if (!q) {
      this.tree.innerHTML = '<p class="tax-suggest-hint muted">Начните вводить код или название</p>';
      return;
    }
    var selected = {};
    this.state.topics.forEach(function (id) { selected[id] = true; });
    var html = '';
    var shown = 0;
    var max = 40;
    var more = false;
    for (var i = 0; i < catalog.topics.length; i += 1) {
      var topic = catalog.topics[i];
      if (!this.isFilter && !topic.leaf) continue;
      if (!matchesQuery(topic, q)) continue;
      if (shown >= max) { more = true; break; }
      shown += 1;
      var cls = 'tax-node is-leaf'
        + (selected[topic.id] ? ' is-selected' : '');
      var extra = topic.leaf ? '' : ' <span class="tax-count">все подтемы</span>';
      var label = (topic.code ? '<span class="tax-code">' + escapeHtml(topic.code)
        + '</span> ' : '') + escapeHtml(topic.name) + extra;
      html += '<div class="' + cls + '">'
        + '<button type="button" data-tax-node="' + topic.id + '">'
        + label + '</button></div>';
    }
    if (!html) html = '<p class="muted">Ничего не найдено</p>';
    else if (more) {
      html += '<p class="tax-suggest-hint muted">Уточните запрос</p>';
    }
    this.tree.innerHTML = html;
  };

  Picker.prototype.syncExtra = function () {
    if (this.facets) this.facets.hidden = !this.facetsOpen;
    if (this.moreBtn) {
      this.moreBtn.hidden = false;
      this.moreBtn.textContent = this.facetsOpen ? 'Скрыть метки' : 'Ещё метки';
    }
  };

  Picker.prototype.render = function () {
    this.renderChips();
    this.renderPanel();
    this.renderGrades();
    if (this.useFacets && !this.compact) this.renderFacets();
    this.syncExtra();
  };

  Picker.prototype.renderChips = function () {
    if (!this.chips) return;
    var html = '';
    var self = this;
    this.state.topics.forEach(function (id) {
      var topic = topicById(id);
      if (!topic) return;
      var full = (topic.code ? topic.code + ' ' : '') + topic.name;
      var label = (!self.chipFull && self.compact && topic.code) ? topic.code : full;
      var isPrimary = self.usePrimary && self.state.primary === id;
      // Код и название — в data-атрибутах: сводка строки каталога берёт их
      // из данных, а не разбирает текст метки (task_catalog.js).
      html += '<span class="tax-chip' + (isPrimary ? ' is-primary' : '') + '"'
        + ' title="' + escapeHtml(full) + '"'
        + ' data-topic-code="' + escapeHtml(topic.code || '') + '"'
        + ' data-topic-name="' + escapeHtml(topic.name || '') + '">';
      if (self.usePrimary) {
        html += '<button type="button" class="tax-chip-star" data-tax-star="'
          + id + '" title="' + (isPrimary ? 'Снять основную тему' : 'Основная тема')
          + '" aria-label="' + (isPrimary ? 'Снять основную тему' : 'Основная тема')
          + '">'
          + (isPrimary ? '★' : '☆') + '</button>';
      }
      html += '<span class="tax-chip-label">' + escapeHtml(label) + '</span>';
      html += '<button type="button" class="tax-chip-x" data-tax-remove="'
        + id + '" aria-label="Убрать">×</button></span>';
    });
    if (!this.state.topics.length) {
      html += '<span class="tax-empty">без темы</span>';
    }
    this.chips.innerHTML = html;
  };

  Picker.prototype.renderTree = function () {
    if (!this.tree || !catalog) return;
    var q = this.query;
    var visible = matchingIds(q);
    var selected = {};
    this.state.topics.forEach(function (id) { selected[id] = true; });
    var html = '';
    var self = this;
    catalog.topics.forEach(function (topic) {
      if (q && !visible[topic.id]) return;
      if (!q && topic.parent && !self.open[topic.parent]) return;
      var isOpen = !!self.open[topic.id] || !!q;
      var cls = 'tax-node tax-depth-' + topic.depth
        + (topic.leaf ? ' is-leaf' : ' is-branch')
        + (selected[topic.id] ? ' is-selected' : '')
        + (isOpen ? ' is-open' : '');
      var count = topic.count ? ' <span class="tax-count">' + topic.count + '</span>' : '';
      var label = (topic.code ? '<span class="tax-code">' + escapeHtml(topic.code)
        + '</span> ' : '') + escapeHtml(topic.name) + count;
      html += '<div class="' + cls + '" style="--depth:' + topic.depth + '">';
      if (self.compact && !topic.leaf) {
        html += '<button type="button" class="tax-twist" data-tax-twist="'
          + topic.id + '" aria-expanded="' + (isOpen ? 'true' : 'false') + '"'
          + ' aria-label="' + (isOpen ? 'Свернуть' : 'Развернуть') + '">'
          + (isOpen ? '▾' : '▸') + '</button>';
      }
      html += '<button type="button" data-tax-node="' + topic.id + '">'
        + label + '</button></div>';
    });
    if (!html) html = '<p class="muted">Ничего не найдено</p>';
    this.tree.innerHTML = html;
  };

  Picker.prototype.gradeButtons = function () {
    var html = '';
    (catalog.grades || []).forEach(function (g) {
      var on = this.state.grades.indexOf(g.code) !== -1;
      var label = g.short || g.name;
      html += '<button type="button" class="tax-toggle tax-toggle-grade'
        + (on ? ' is-on' : '') + '" data-tax-grade="'
        + escapeHtml(g.code) + '" title="' + escapeHtml(g.name) + '">'
        + escapeHtml(label) + '</button>';
    }, this);
    return html;
  };

  Picker.prototype.renderGrades = function () {
    if (!this.useGrades || !this.gradesEl || !catalog) return;
    this.gradesEl.innerHTML = this.gradeButtons();
  };

  Picker.prototype.renderFacets = function () {
    if (!this.facets || !catalog) return;
    var html = '';

    html += '<div class="tax-facet"><span class="tax-facet-label">Уровень</span><div class="tax-facet-row">';
    (catalog.levels || []).forEach(function (g) {
      var on = this.state.facets.indexOf(g.id) !== -1;
      html += '<button type="button" class="tax-toggle' + (on ? ' is-on' : '')
        + '" data-tax-facet="' + g.id + '">' + escapeHtml(g.name) + '</button>';
    }, this);
    html += '</div></div>';

    html += '<div class="tax-facet"><span class="tax-facet-label">Метод</span><div class="tax-facet-row">';
    (catalog.methods || []).forEach(function (g) {
      var on = this.state.facets.indexOf(g.id) !== -1;
      html += '<button type="button" class="tax-toggle' + (on ? ' is-on' : '')
        + '" data-tax-facet="' + g.id + '">' + escapeHtml(g.name) + '</button>';
    }, this);
    html += '</div></div>';

    (catalog.exams || []).forEach(function (model) {
      html += '<div class="tax-facet"><span class="tax-facet-label">'
        + escapeHtml(model.name) + '</span><div class="tax-facet-row">';
      model.items.forEach(function (item) {
        var on = this.state.exams.indexOf(item.id) !== -1;
        var line = isExamLine(item);
        var label = line ? 'без №' : String(item.item_number);
        html += '<button type="button" class="tax-toggle'
          + (line ? ' tax-toggle-exam-line' : '')
          + (on ? ' is-on' : '')
          + '" data-tax-exam="' + item.id + '" title="'
          + escapeHtml(item.name) + '">' + escapeHtml(label) + '</button>';
      }, this);
      html += '</div></div>';
    }, this);

    if (!this.isFilter) {
      html += '<div class="tax-facet"><span class="tax-facet-label">Сложность 1–5</span><div class="tax-facet-row">';
      html += '<button type="button" class="tax-toggle'
        + (this.state.difficulty == null ? ' is-on' : '')
        + '" data-tax-diff="">—</button>';
      for (var i = 1; i <= 5; i += 1) {
        html += '<button type="button" class="tax-toggle'
          + (this.state.difficulty === i ? ' is-on' : '')
          + '" data-tax-diff="' + i + '">' + i + '</button>';
      }
      html += '</div></div>';
    }
    this.facets.innerHTML = html;
  };

  Picker.prototype.getField = function (name) {
    if (name === 'topics' || name === 'topic') return this.state.topics.map(String);
    if (name === 'primary_topic') return this.state.primary == null ? '' : String(this.state.primary);
    if (name === 'grade_bands' || name === 'grade') return this.state.grades.slice();
    if (name === 'facet_values') return this.state.facets.map(String);
    if (name === 'exam_items') return this.state.exams.map(String);
    if (name === 'difficulty') return this.state.difficulty == null ? '' : String(this.state.difficulty);
    return null;
  };

  Picker.prototype.setField = function (name, value) {
    if (name === 'topics') {
      this.state.topics = (value || []).map(Number);
      if (this.usePrimary && this.state.topics.indexOf(this.state.primary) === -1) {
        this.state.primary = this.state.topics[0] || null;
      }
    } else if (name === 'primary_topic') {
      this.state.primary = value ? Number(value) : null;
    } else if (name === 'grade_bands') {
      this.state.grades = (value || []).slice();
    } else if (name === 'facet_values') {
      this.state.facets = (value || []).map(Number);
    } else if (name === 'exam_items') {
      this.state.exams = (value || []).map(Number);
      if (!this.isFilter) {
        this.state.exams = ensureExamParentIds(this.state.exams);
      }
    } else if (name === 'difficulty') {
      this.state.difficulty = value ? Number(value) : null;
    } else {
      return false;
    }
    this.syncHidden();
    this.render();
    return true;
  };

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function init() {
    if (!loadCatalog()) {
      fetchCatalog().then(function (data) {
        if (data) initPickers();
        else showLoadError();
      });
      return;
    }
    initPickers();
  }

  function initPickers() {
    clearLoadError();
    pickers = pickers.filter(function (p) { return p.form && p.form.isConnected; });
    var created = [];
    document.querySelectorAll('[data-tax-picker]').forEach(function (el) {
      if (el.dataset.taxReady) return;
      el.dataset.taxReady = '1';
      var picker = new Picker(el);
      pickers.push(picker);
      created.push(picker);
    });
    readyResolve();
    if (created.length) {
      document.dispatchEvent(new CustomEvent('egor:taxonomy-ready', {
        detail: {forms: created.map(function (p) { return p.form; })}
      }));
    }
  }

  function findPicker(form, name) {
    for (var i = 0; i < pickers.length; i += 1) {
      if (pickers[i].form === form && pickers[i].getField(name) !== null) {
        return pickers[i];
      }
    }
    return null;
  }

  window.EgorTaxonomy = {
    init: init,
    ready: function () { return readyPromise; },
    get: function (form, name) {
      var p = findPicker(form, name);
      return p ? p.getField(name) : null;
    },
    set: function (form, name, value) {
      var p = findPicker(form, name);
      return p ? p.setField(name, value) : false;
    },
    has: function (form, name) {
      return !!findPicker(form, name);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
