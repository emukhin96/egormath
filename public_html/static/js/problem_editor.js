/* Общие действия редактора задачи: блоки, область сохранения, обновление. */
(function () {
  'use strict';
  function toast(ok, text) { window.EgorAutosave.showSaved(ok, text); }
  function endpoint(root) {
    var url = new URL(root.dataset.manageUrl, location.href);
    if(root.matches('[data-problem-editor]'))url.searchParams.set('view', 'task');
    if (root.dataset.item) {
      url.searchParams.set('worksheet', root.dataset.worksheet);
      url.searchParams.set('item', root.dataset.item);
    }
    return url;
  }
  async function request(url, body) {
    var options = {credentials: 'same-origin'};
    if (body) {
      options.method = 'POST'; options.body = body;
      options.headers = {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
        'X-Requested-With': 'XMLHttpRequest'};
    }
    var response = await fetch(url, options);
    var result;
    try { result = await response.json(); }
    catch (_) { throw new Error('Сервер не ответил. Обновите страницу и повторите.'); }
    if (!response.ok || result.ok === false) {
      var error = new Error(result.message || result.error || 'Не удалось сохранить');
      error.fields = result.errors; throw error;
    }
    return result;
  }
  function errors(container, error) {
    container.textContent = '';
    Object.entries(error.fields || {'': [error.message]}).forEach(function (pair) {
      var p = document.createElement('p');
      p.textContent = (pair[0] && pair[0] !== '__all__' ? pair[0] + ': ' : '') + pair[1].join('; ');
      container.appendChild(p);
    });
  }
  function chooseScope(root) {
    if (!root.dataset.item) return Promise.resolve('global');
    return new Promise(function (resolve) {
      var dialog = document.getElementById('answer-scope-dialog'), choice = null;
      function click(e) { var b = e.target.closest('[data-save-scope]'); if (b) { choice = b.dataset.saveScope; dialog.close(); } }
      dialog.addEventListener('click', click);
      dialog.addEventListener('close', function () { dialog.removeEventListener('click', click); resolve(choice); }, {once:true});
      dialog.showModal();
    });
  }
  function formKey(form) {
    return form.querySelector('[name=block]').value + ':' + (form.querySelector('[name=subitem]')?.value || '');
  }
  function update(result, submitted) {
    var root = document.querySelector('[data-problem-editor]');
    if (!root) { location.reload(); return; }
    var dirty = Array.from(root.querySelectorAll('form[data-dirty]')).filter(f => f !== submitted);
    var template = document.createElement('template'); template.innerHTML = result.html;
    var next = template.content.querySelector('[data-problem-editor]');
    // Несохранённые соседние блоки не теряются при сохранении текущего.
    if (root.dataset.taskId === String(result.task_id)) {
      dirty.forEach(function (old) {
        var fresh = Array.from(next.querySelectorAll('[data-editor-form]')).find(f => formKey(f) === formKey(old));
        if (fresh) {
          fresh.replaceWith(old);
          for (var el = old.parentElement; el && el !== next; el = el.parentElement) if (el.tagName === 'DETAILS') el.open = true;
        }
      });
    }
    root.replaceWith(next);
    var sidebar=document.querySelector('[data-problem-sidebar]');
    if(sidebar && result.sidebar)sidebar.innerHTML=result.sidebar;
    history.replaceState(null, '', result.url);
    next.querySelectorAll('.math-content').forEach(renderMathContent);
    window.EgorTaxonomy.init(); window.EgorTaskForm.init();
    document.title = 'Задача #' + result.task_id + ' — Математика';
    toast(true, 'Сохранено ✓');
  }
  async function save(root, data, form) {
    var scope = await chooseScope(root); if (!scope) return null;
    if (scope === 'local' && document.querySelectorAll('[data-problem-editor] form[data-dirty]').length > (form?.dataset.dirty ? 1 : 0)) {
      throw new Error('Сначала сохраните или отмените правки других блоков, затем создайте локальную копию.');
    }
    data.set('scope', scope);
    var result = await request(endpoint(root), data);
    update(result, form); return result;
  }
  document.addEventListener('input', function (e) { var f=e.target.closest('[data-editor-form]'); if(f)f.dataset.dirty='1'; });
  document.addEventListener('change', function (e) { var f=e.target.closest('[data-editor-form]'); if(f){f.dataset.dirty='1';if(f.hasAttribute('data-editor-auto'))f.requestSubmit();} });
  document.addEventListener('submit', async function (e) {
    var form=e.target.closest('[data-editor-form]'); if(!form)return;
    e.preventDefault();
    if(form.dataset.busy)return;
    form.dataset.busy='1'; var button=e.submitter; if(button)button.disabled=true;
    var box=form.querySelector('[data-editor-errors]');box.textContent='';
    var data=new FormData(form), toggle=form.hasAttribute('data-editor-auto')&&form.querySelector('input[type=checkbox]');
    if(toggle)toggle.disabled=true;
    try { var result=await save(form.closest('[data-problem-editor]'), data, form); if(!result&&form.hasAttribute('data-editor-auto')){form.reset();delete form.dataset.dirty;} }
    catch(error){if(form.hasAttribute('data-editor-auto')){form.reset();delete form.dataset.dirty;}errors(box,error);}
    finally { delete form.dataset.busy; if(button)button.disabled=false; if(toggle)toggle.disabled=false; }
  });
  document.addEventListener('click', async function(e){
    var cancel=e.target.closest('[data-editor-cancel]');
    if(cancel){
      var form=cancel.closest('form');
      // Восстановление серверной формы возвращает также формсеты и рубрикатор.
      try {
        var html=await fetch(location.href).then(r=>r.text());
        var doc=new DOMParser().parseFromString(html,'text/html');
        var fresh=Array.from(doc.querySelectorAll('[data-editor-form]')).find(f=>formKey(f)===formKey(form));
        if(fresh){form.replaceWith(fresh);window.EgorTaxonomy.init();window.EgorTaskForm.init();}
      }catch(error){toast(false,'Не удалось восстановить блок');}
    }
    var ai=e.target.closest('[data-editor-ai]');if(!ai)return;
    var root=ai.closest('[data-problem-editor]');ai.disabled=true;
    try {
      if(root.querySelector('[name=block][value=subitems]').form.dataset.dirty) {
        throw new Error('Сохраните подпункты перед генерацией, чтобы ответы соответствовали их порядку.');
      }
      var response=await fetch(window.NEURO_SOLVE_URL,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify({task_id:Number(root.dataset.taskId),text:root.querySelector('[name=text_latex]').value})});
      var result=await response.json();if(!response.ok||result.error)throw new Error(result.error||'Не удалось получить AI-ответ');
      root.querySelectorAll('[data-answer-owner]').forEach(function(section,i){
        var isSub=Boolean(section.dataset.answerOwner);
        [['answer_latex',isSub?(result.subitem_answers||[])[i]:result.answer],['solution_latex',isSub?(result.subitem_solutions||[])[i]:result.solution]].forEach(function(pair){
          if(pair[0]==='solution_latex'&&ai.dataset.editorAi==='answer')return;
          var field=section.querySelector('[name="'+pair[0]+'"]');
          if(field&&pair[1]&&!field.value.trim()){
            field.value=pair[1];field.dispatchEvent(new Event('input',{bubbles:true}));
            for(var el=field.parentElement;el&&el!==root;el=el.parentElement)if(el.tagName==='DETAILS')el.open=true;
          }
        });
      });toast(true,'AI-черновик в пустых полях — проверьте и сохраните блоки');
    }catch(error){toast(false,error.message);}finally{ai.disabled=false;}
  });
  window.EgorProblem={request,endpoint,errors,save,toast};
})();
