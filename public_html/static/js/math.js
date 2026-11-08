// Рендер математики KaTeX внутри элементов с классом .math-content.
// Команды egor.sty, которых KaTeX не знает, остаются текстом (throwOnError:false).
// Десятичную запятую (0,6) защищаем как {,}: иначе KaTeX ставит пробел.
// Нужно и здесь: часть шаблонов кладёт сырой TeX в .math-content без web_text.
function protectDecimalCommas(html) {
  return html.replace(
    /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\$[^$]*\$|\\\([\s\S]*?\\\))/g,
    function (math) {
      return math.replace(/(\d),(\d)/g, '$1{,}$2');
    }
  );
}

// Тот же рендер для разметки, вставленной скриптами (превью маски и т.п.)
var renderedMathContents = new WeakMap();
function renderMathContent(el) {
  if (typeof renderMathInElement !== 'function') return;
  if (el.closest('.ws-answers[hidden]')) return;
  if (renderedMathContents.get(el) === el.innerHTML) return;
  el.innerHTML = protectDecimalCommas(el.innerHTML);
  renderMathInElement(el, {
    delimiters: [
      {left: '$$', right: '$$', display: true},
      {left: '\\[', right: '\\]', display: true},
      {left: '$', right: '$', display: false},
      {left: '\\(', right: '\\)', display: false},
    ],
    // Команды egor.sty, которых KaTeX не знает
    macros: {'\\degr': '^{\\circ}', '\\divby': '\\mathrel{\\mathchoice{\\footnotesize\\varvdots}{\\footnotesize\\varvdots}{\\scriptscriptstyle\\varvdots}{\\scriptscriptstyle\\varvdots}}'},
    throwOnError: false,
  });
  // Запоминаем результат, а не флаг: после редактирования рендер нужен снова.
  renderedMathContents.set(el, el.innerHTML);
}

// Ленивый рендер больших страниц (быстродействие 11.2026): на книжном листке
// 6 800 формул, и рендер всех сразу держал DOMContentLoaded ~5 с. Если блоков
// .math-content больше LAZY_THRESHOLD, сразу рендерятся только блоки в
// пределах LAZY_SCREENS экранов от видимой области, остальные —
// IntersectionObserver'ом при приближении (запас — тот же rootMargin).
// Маленькие страницы ведут себя как раньше: всё сразу, наблюдателя нет.
// До рендера блок показывает исходный TeX ($…$): поиск по странице (Ctrl-F)
// найдёт его, копирование даст тот же $…$, что katex_copy.js делает из формул.
var LAZY_THRESHOLD = 300;
var LAZY_SCREENS = 1.5;
var lazyMathObserver = null;
var lazyMathPending = new Set();

function observeMathContent(el) {
  if (!lazyMathObserver) { renderMathContent(el); return; }
  lazyMathPending.add(el);
  lazyMathObserver.observe(el);
}

function renderLazyMath(el) {
  if (lazyMathObserver) lazyMathObserver.unobserve(el);
  lazyMathPending.delete(el);
  renderMathContent(el);
}

// Все отложенные блоки сразу — перед печатью и для снимков целиком
function renderAllMath(root) {
  if (root) {
    root.querySelectorAll('.math-content').forEach(renderLazyMath);
    if (root.matches && root.matches('.math-content')) renderLazyMath(root);
    return;
  }
  Array.from(lazyMathPending).forEach(renderLazyMath);
}

function startLazyMath(blocks) {
  lazyMathObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) renderLazyMath(entry.target);
    });
  }, {rootMargin: Math.round(LAZY_SCREENS * 100) + '% 0px'});
  // Положение всех блоков читается до первого рендера: каждый рендер меняет
  // раскладку, и чередование чтения с записью стоило бы 6 800 перерасчётов
  var margin = window.innerHeight * LAZY_SCREENS;
  var near = blocks.map(function (el) {
    var rect = el.getBoundingClientRect();
    // Скрытый блок (display:none, размеров нет) рендерится сразу, как раньше:
    // наблюдатель его не увидит, а показать его может любой скрипт
    return (rect.width === 0 && rect.height === 0)
      || (rect.bottom > -margin && rect.top < window.innerHeight + margin);
  });
  blocks.forEach(function (el, index) {
    if (near[index]) renderMathContent(el); else observeMathContent(el);
  });
  window.addEventListener('beforeprint', function () { renderAllMath(); });
}

window.EgorMath = {
  render: renderMathContent,
  observe: observeMathContent,
  renderAll: renderAllMath,
  isLazy: function () { return lazyMathObserver !== null; },
};

document.addEventListener('DOMContentLoaded', function () {
  var blocks = Array.from(document.querySelectorAll('.math-content'));
  if (blocks.length > LAZY_THRESHOLD && typeof IntersectionObserver === 'function') {
    startLazyMath(blocks);
  } else {
    blocks.forEach(renderMathContent);
  }
});
