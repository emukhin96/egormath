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
    macros: {'\\degr': '^{\\circ}'},
    throwOnError: false,
  });
  // Запоминаем результат, а не флаг: после редактирования рендер нужен снова.
  renderedMathContents.set(el, el.innerHTML);
}

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.math-content').forEach(renderMathContent);
});
