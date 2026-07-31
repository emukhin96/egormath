// Рендер математики KaTeX внутри элементов с классом .math-content.
// Команды egor.sty, которых KaTeX не знает, остаются текстом (throwOnError:false).
document.addEventListener('DOMContentLoaded', function () {
  if (typeof renderMathInElement !== 'function') return;
  document.querySelectorAll('.math-content').forEach(function (el) {
    renderMathInElement(el, {
      delimiters: [
        {left: '$$', right: '$$', display: true},
        {left: '\\[', right: '\\]', display: true},
        {left: '$', right: '$', display: false},
        {left: '\\(', right: '\\)', display: false},
      ],
      throwOnError: false,
    });
  });
});
