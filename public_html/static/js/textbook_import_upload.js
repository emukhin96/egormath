(() => {
  const form = document.querySelector('[data-textbook-upload]');
  if (!form) return;

  const radios = [...form.querySelectorAll('input[name="input_kind"]')];
  const panels = [...form.querySelectorAll('[data-input-panel]')];

  function refresh() {
    const selected = radios.find((radio) => radio.checked)?.value || 'json';
    panels.forEach((panel) => {
      const kinds = panel.dataset.inputPanel.split(/\s+/);
      panel.hidden = !kinds.includes(selected);
    });
  }

  radios.forEach((radio) => radio.addEventListener('change', refresh));
  refresh();
})();
