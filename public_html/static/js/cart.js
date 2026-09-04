/* Корзина задач: кнопки «+» у задач (формы [data-cart-form]) шлют fetch
   вместо перезагрузки страницы и обновляют счётчик в шапке.
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

  function renderButton(form, inCart) {
    var button = form.querySelector('.cart-btn');
    form.dataset.inCart = inCart ? '1' : '0';
    form.action = inCart ? form.dataset.removeUrl : form.dataset.addUrl;
    button.classList.toggle('is-in-cart', inCart);
    button.textContent = inCart ? '✓' : '+';
    button.title = inCart ? 'В корзине — нажмите, чтобы убрать' : 'В корзину — чтобы собрать листок';
    button.setAttribute('aria-label', inCart ? 'Убрать из корзины' : 'В корзину');
  }

  function renderMenu(count) {
    var badge = document.querySelector('[data-cart-count]');
    if (badge) {
      badge.textContent = count;
      badge.hidden = !count;
    }
    var title = document.querySelector('[data-cart-title]');
    if (title) title.textContent = count ? 'Задач в корзине: ' + count : 'Корзина пуста';
    document.querySelectorAll('[data-cart-needs-items]').forEach(function (b) {
      b.disabled = !count;
    });
    var clear = document.querySelector('[data-cart-clear]');
    if (clear) clear.hidden = !count;
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
        toast(false, result.data.message || 'Не удалось изменить корзину');
        return;
      }
      renderButton(form, result.data.in_cart);
      renderMenu(result.data.count);
      toast(true, result.data.message);
    }).catch(function () {
      toast(false, 'Нет связи — корзина не изменена');
    }).then(function () {
      button.disabled = false;
    });
  });
})();
