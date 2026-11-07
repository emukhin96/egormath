/* Корзина задач: кнопки «+» у задач (формы [data-cart-form]) и «×» в меню
   (формы [data-cart-remove]) шлют fetch вместо перезагрузки страницы и
   обновляют счётчик и меню в шапке.
   Без JS формы работают как обычные POST с redirect.
   Панель действий задачи (includes/task_actions.html) ставит не форму, а
   <span data-cart-form data-cart-js data-task-id> с кнопкой type=button:
   её можно класть внутрь чужой формы (страница проверки целиком — форма),
   запрос собирается здесь же. */
(function () {
  'use strict';

  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) {
      EgorAutosave.showSaved(ok, message);
    } else if (!ok) {
      window.alert(message);
    }
  }

  function cartButton(form) {
    return form.querySelector('[data-cart-button]') || form.querySelector('.cart-btn');
  }

  function renderButton(form, inCart) {
    var button = cartButton(form);
    form.dataset.inCart = inCart ? '1' : '0';
    if (form.tagName === 'FORM') form.action = inCart ? form.dataset.removeUrl : form.dataset.addUrl;
    button.classList.toggle('is-in-cart', inCart);
    // Кнопка с подписью (панель действий задачи) — «+ В корзину» / «✓ В корзине»
    if (button.dataset.labelAdd) {
      button.textContent = inCart ? button.dataset.labelIn : button.dataset.labelAdd;
    } else {
      button.textContent = inCart ? '✓' : '+';
    }
    button.title = inCart ? 'В корзине — нажмите, чтобы убрать' : 'В корзину — чтобы собрать листок';
    button.setAttribute('aria-label', inCart ? 'Убрать из корзины' : 'В корзину');
  }

  // Корзина лежит в сессии: два одновременных запроса читают одну и ту же
  // корзину, и последний ответ затирает задачу из первого (быстрые клики
  // «+» по нескольким задачам). Поэтому запросы корзины — строго по очереди.
  var queue = Promise.resolve();
  function enqueue(send) {
    var result = queue.then(send, send);
    queue = result.catch(function () {});
    return result;
  }

  // Отметка «+»/«✓» у всех кнопок задач из ответа сервера: у задачи блока
  // меняется весь блок (task_ids), а не только нажатая кнопка.
  function renderButtons(taskIds, inCart) {
    var ids = (taskIds || []).map(String);
    document.querySelectorAll('[data-cart-form]').forEach(function (f) {
      var input = f.querySelector('[name=task_id]');
      var id = f.dataset.taskId || (input && input.value);
      if (id && ids.indexOf(id) !== -1) renderButton(f, inCart);
    });
  }

  // Меню корзины (список задач, точки семей) собирает сервер: после «+»/«×»
  // просим свежую разметку cart_panel. Закрытое меню — при следующем открытии.
  // Запрос панели идёт в той же очереди, что и изменения корзины, а ответ,
  // обогнанный более новым запросом, отбрасывается (panelSeq).
  var panelStale = false;
  var panelSeq = 0;

  function refreshPanel() {
    var menu = document.querySelector('[data-cart-menu]');
    if (!menu || !menu.dataset.panelUrl) return;
    if (!menu.open) {
      panelStale = true;
      return;
    }
    panelStale = false;
    var seq = ++panelSeq;
    var url = menu.dataset.panelUrl + '?next=' +
      encodeURIComponent(window.location.pathname + window.location.search);
    enqueue(function () {
      return fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
        .then(function (r) { return r.ok ? r.text() : Promise.reject(r); });
    })
      .then(function (html) {
        if (seq !== panelSeq) return;
        var old = menu.querySelector('[data-cart-panel]');
        var box = document.createElement('div');
        box.innerHTML = html.trim();
        var fresh = box.querySelector('[data-cart-panel]');
        if (!old || !fresh) return;
        old.replaceWith(fresh);
        if (typeof renderMathContent === 'function') {
          fresh.querySelectorAll('.math-content').forEach(renderMathContent);
        }
      })
      .catch(function () { if (seq === panelSeq) panelStale = true; });
  }

  function renderMenu(count) {
    var badge = document.querySelector('[data-cart-count]');
    if (badge) {
      badge.textContent = count;
      badge.hidden = !count;
    }
    refreshPanel();
  }

  var menu = document.querySelector('[data-cart-menu]');
  if (menu) {
    menu.addEventListener('toggle', function () {
      if (menu.open && panelStale) refreshPanel();
    });
  }

  // «×» в меню: убрать задачу без перезагрузки и снять отметку «✓» у её «+»
  // (у задачи блока — у всего блока)
  document.addEventListener('submit', function (e) {
    var form = e.target.closest ? e.target.closest('[data-cart-remove]') : null;
    if (!form) return;
    e.preventDefault();
    var taskId = form.querySelector('[name=task_id]').value;
    var body = new FormData(form);
    enqueue(function () {
      return fetch(form.action, {
        method: 'POST',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        body: body,
      });
    }).then(function (r) {
      return r.json().then(function (data) { return {ok: r.ok && data.ok, data: data}; });
    }).then(function (result) {
      if (!result.ok) {
        toast(false, result.data.message || 'Не удалось изменить корзину');
        return;
      }
      renderButtons(result.data.task_ids || [taskId], false);
      renderMenu(result.data.count);
    }).catch(function () {
      toast(false, 'Нет связи — корзина не изменена');
    });
  });

  function toggle(form, url, body, headers) {
    var button = cartButton(form);
    button.disabled = true;
    headers['X-Requested-With'] = 'XMLHttpRequest';
    enqueue(function () {
      return fetch(url, {method: 'POST', headers: headers, body: body});
    }).then(function (r) {
      return r.json().then(function (data) { return {ok: r.ok && data.ok, data: data}; });
    }).then(function (result) {
      if (!result.ok) {
        toast(false, result.data.message || 'Не удалось изменить корзину');
        return;
      }
      renderButton(form, result.data.in_cart);
      renderButtons(result.data.task_ids, result.data.in_cart);
      renderMenu(result.data.count);
      toast(true, result.data.message);
    }).catch(function () {
      toast(false, 'Нет связи — корзина не изменена');
    }).then(function () {
      button.disabled = false;
    });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest ? e.target.closest('form[data-cart-form]') : null;
    if (!form) return;
    e.preventDefault();
    toggle(form, form.action, new FormData(form), {});
  });

  // Кнопка панели действий: без формы, адрес — по текущему состоянию
  document.addEventListener('click', function (e) {
    var button = e.target.closest ? e.target.closest('[data-cart-js] [data-cart-button]') : null;
    if (!button) return;
    e.preventDefault();
    var box = button.closest('[data-cart-js]');
    var body = new FormData();
    body.append('task_id', box.dataset.taskId);
    var url = box.dataset.inCart === '1' ? box.dataset.removeUrl : box.dataset.addUrl;
    toggle(box, url, body, {'X-CSRFToken': box.dataset.csrf});
  });
})();
