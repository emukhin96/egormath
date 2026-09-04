/* Корзина листка: кнопки «в листок» у задач (формы [data-cart-form]) шлют
   fetch вместо перезагрузки страницы и обновляют индикатор в шапке.
   Без JS формы работают как обычные POST с redirect. */
(function () {
  'use strict';

  function toast(ok, message) {
    if (window.EgorAutosave && EgorAutosave.showSaved) {
      EgorAutosave.showSaved(ok, message);
    } else if (!ok) {
      window.alert(message);
    }
  }

  function truncate(text, limit) {
    return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
  }

  function renderButton(form, inCart, title) {
    var button = form.querySelector('.cart-btn');
    form.dataset.inCart = inCart ? '1' : '0';
    form.action = inCart ? form.dataset.removeUrl : form.dataset.addUrl;
    button.classList.toggle('is-in-cart', inCart);
    button.textContent = inCart ? '✓ в листке' : '+ в листок';
    button.title = inCart
      ? 'Уже в листке «' + title + '» — нажмите, чтобы убрать'
      : 'Добавить в конец листка «' + title + '»';
  }

  function renderMenu(data) {
    var title = document.querySelector('[data-cart-title]');
    var count = document.querySelector('[data-cart-count]');
    if (title) title.textContent = truncate(data.worksheet.title, 24);
    if (count) {
      count.textContent = data.count;
      count.hidden = false;
    }
    document.querySelectorAll('[data-cart-link]').forEach(function (a) {
      a.href = data.worksheet.url;
    });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest ? e.target.closest('[data-cart-form]') : null;
    if (!form) return;
    e.preventDefault();
    var button = form.querySelector('.cart-btn');
    button.disabled = true;
    fetch(form.action, {
      method: 'POST',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      body: new FormData(form),
    }).then(function (r) {
      return r.json().then(function (data) { return {ok: r.ok && data.ok, data: data}; });
    }).then(function (result) {
      if (!result.ok) {
        toast(false, result.data.message || 'Не удалось изменить листок');
        return;
      }
      renderButton(form, result.data.in_cart, result.data.worksheet.title);
      renderMenu(result.data);
      toast(true, result.data.message);
    }).catch(function () {
      toast(false, 'Нет связи — листок не изменён');
    }).then(function () {
      button.disabled = false;
    });
  });
})();
