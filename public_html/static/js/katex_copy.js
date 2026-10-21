/* Копирование текста с формулами KaTeX. Рядом с видимой формулой KaTeX
   держит её MathML-копию с исходником, и браузер копирует всё сразу:
   «x2+1x^2+1». В буфер уходит текст, где каждая формула — один раз,
   исходным LaTeX в $…$. Тот же текст пишет журнал работы (work_activity.js). */
(function () {
  'use strict';
  const BLOCKS = 'p, div, li, br, h1, h2, h3, h4, tr, .katex-display';
  const KATEX_PARTS = '.katex, .katex-mathml, .katex-html';

  function element(node) {
    return node.nodeType === 1 ? node : node.parentElement;
  }
  // Выделение, начатое или законченное внутри формулы, расширяется до всей
  // формулы — иначе в буфер попадут обрывки её разметки.
  function wholeFormulas(range) {
    const result = range.cloneRange();
    const start = element(result.startContainer)?.closest('.katex');
    const end = element(result.endContainer)?.closest('.katex');
    if (start) result.setStartBefore(start);
    if (end) result.setEndAfter(end);
    return result;
  }
  function texOf(formula) {
    const tex = formula.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
    // math.js защищает десятичную запятую как {,} — в буфер она идёт обычной
    return tex == null ? '' : tex.replace(/(\d)\{,\}(?=\d)/g, '$1,').trim();
  }
  // Текст диапазона: формулы — LaTeX, абзацы — с новой строки. `drop` —
  // селектор того, что выбросить (номера задач и звёзды в журнале работы).
  function plainText(range, drop = '') {
    const fragment = wholeFormulas(range).cloneContents();
    fragment.querySelectorAll('.katex').forEach(formula => {
      const tex = texOf(formula);
      const display = formula.parentElement?.classList.contains('katex-display');
      formula.replaceWith(!tex ? '' : display ? `$$${tex}$$` : `$${tex}$`);
    });
    // Остатки формул без корня .katex (если вдруг) не должны дать дубль
    fragment.querySelectorAll('.katex-mathml, .katex-html').forEach(node => node.remove());
    fragment.querySelectorAll('script, style, button, [aria-hidden="true"]' + (drop ? ', ' + drop : ''))
      .forEach(node => node.remove());
    // Переводы строк исходного HTML — просто пробелы, как и на экране
    const walker = document.createTreeWalker(fragment, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      node.textContent = node.textContent.replace(/\s+/g, ' ');
    }
    fragment.querySelectorAll(BLOCKS).forEach(node => node.append('\n'));
    return fragment.textContent.replace(/ *\n[\s]*/g, '\n').replace(/ {2,}/g, ' ').trim();
  }
  function selectionText(selection, drop = '') {
    const parts = [];
    for (let i = 0; i < selection.rangeCount; i++) parts.push(plainText(selection.getRangeAt(i), drop));
    return parts.filter(Boolean).join('\n');
  }
  function hasFormula(selection) {
    for (let i = 0; i < selection.rangeCount; i++) {
      const range = selection.getRangeAt(i);
      if (element(range.startContainer)?.closest('.katex') || element(range.endContainer)?.closest('.katex')) return true;
      if (range.cloneContents().querySelector(KATEX_PARTS)) return true;
    }
    return false;
  }

  // Всплытие: журнал работы ловит копирование раньше (на захвате) и при
  // подмене чисел или запрете сам решает, что окажется в буфере.
  document.addEventListener('copy', event => {
    if (event.defaultPrevented || !event.clipboardData) return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount || !hasFormula(selection)) return;
    event.clipboardData.setData('text/plain', selectionText(selection));
    event.preventDefault();
  });

  window.EgorCopy = {plainText, selectionText};
})();
