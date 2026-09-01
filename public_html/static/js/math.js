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

document.addEventListener('DOMContentLoaded', function () {
  if (typeof renderMathInElement !== 'function') return;
  document.querySelectorAll('.math-content').forEach(function (el) {
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
  });
});
