/* Увеличенный просмотр картинок задач: клик (или Enter/пробел) по картинке
   в .task-images открывает её в диалоге во весь экран. Закрытие — крестик,
   клик по картинке или фону, Esc (нативное поведение <dialog>). Мелкие
   оригиналы растягиваются не больше чем втрое, чтобы не превращаться в кашу. */
(function () {
  'use strict';

  var SELECTOR = '.task-images img';
  var MAX_UPSCALE = 3;
  var dialog = null;
  var picture = null;

  function build() {
    dialog = document.createElement('dialog');
    dialog.className = 'image-zoom';
    dialog.setAttribute('aria-label', 'Увеличенная картинка');
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'icon-btn image-zoom-close';
    close.setAttribute('aria-label', 'Закрыть');
    close.textContent = '×';
    picture = document.createElement('img');
    picture.alt = '';
    dialog.appendChild(close);
    dialog.appendChild(picture);
    // Любой клик внутри (крестик, картинка, фон-backdrop) закрывает просмотр.
    dialog.addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('close', function () { picture.removeAttribute('src'); });
    document.body.appendChild(dialog);
  }

  function fit() {
    var w = picture.naturalWidth, h = picture.naturalHeight;
    if (!w || !h) return;
    var scale = Math.min(window.innerWidth * 0.92 / w, window.innerHeight * 0.88 / h, MAX_UPSCALE);
    picture.style.width = Math.round(w * scale) + 'px';
    picture.style.height = Math.round(h * scale) + 'px';
  }

  function open(img) {
    if (!dialog) build();
    if (typeof dialog.showModal !== 'function') {
      window.open(img.currentSrc || img.src, '_blank', 'noopener');
      return;
    }
    picture.style.width = picture.style.height = '';
    picture.onload = fit;
    picture.src = img.currentSrc || img.src;
    picture.alt = img.alt || '';
    dialog.showModal();
    if (picture.complete) fit();
  }

  function mark(root) {
    (root || document).querySelectorAll(SELECTOR).forEach(function (img) {
      if (img.hasAttribute('data-zoomable')) return;
      img.setAttribute('data-zoomable', '');
      img.setAttribute('tabindex', '0');
      img.setAttribute('role', 'button');
      img.setAttribute('title', 'Увеличить');
    });
  }

  document.addEventListener('click', function (e) {
    var img = e.target.closest && e.target.closest(SELECTOR);
    if (!img || img.closest('a')) return;
    e.preventDefault();
    open(img);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var img = e.target.closest && e.target.closest(SELECTOR);
    if (!img) return;
    e.preventDefault();
    open(img);
  });
  window.addEventListener('resize', function () {
    if (dialog && dialog.open) fit();
  });
  // Тот же просмотр для картинок вне .task-images — фото решения в
  // самостоятельной открываются здесь, а не в новой вкладке (iw_leave_lock.js)
  window.EgorImageZoom = { open: open };

  // Картинки появляются и после загрузки страницы (подгрузка подборок,
  // диалоги прогресса) — размечаем их для клавиатуры по мере появления.
  document.addEventListener('DOMContentLoaded', function () {
    mark();
    var pending = false;
    new MutationObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () { pending = false; mark(); });
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
