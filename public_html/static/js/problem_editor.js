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
  // Общая задача у приглашённого учителя (data-base-locked): в листке правки
  // сразу уходят в локальную копию, без листка — подсказка, как её получить
  // (accounts/permissions.py), и ссылка «Предложить исправление» на страницу
  // предложения этой задачи (problems/proposals.py).
  function baseLocked(root) {
    var dialog = document.getElementById('base-locked-dialog');
    if (!dialog) return Promise.reject(new Error('Общая задача: измените её для своего листка.'));
    var input = dialog.querySelector('[name=task_id]');
    if (input) input.value = root.dataset.taskId || '';
    var propose = dialog.querySelector('[data-propose-link]');
    if (propose && propose.dataset.urlTemplate) {
      propose.href = propose.dataset.urlTemplate.replace('/0/', '/' + (root.dataset.taskId || '0') + '/')
        + '?next=' + encodeURIComponent(location.pathname + location.search);
    }
    return new Promise(function (resolve) {
      dialog.addEventListener('close', function () { resolve(null); }, {once: true});
      dialog.showModal();
    });
  }
  function chooseScope(root) {
    if (root.dataset.baseLocked) return root.dataset.item ? Promise.resolve('local') : baseLocked(root);
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
  async function updateWorksheet(source) {
    // Серверная строка содержит новые URL и ID подпунктов локальной копии.
    // Обновляем также соседние вопросы скопированного блока и повторы задачи.
    var response = await fetch(location.href, {credentials: 'same-origin'});
    if (!response.ok || response.redirected) throw new Error('Не удалось обновить листок');
    var doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    if (!doc.querySelector('#ws-items')) throw new Error('Не удалось обновить листок');
    document.querySelectorAll('#ws-items > .ws-item[data-task-id]').forEach(function (row) {
      var fresh = doc.querySelector('#ws-items > .ws-item[data-id="' + row.dataset.id + '"]');
      if (!fresh || (row.dataset.taskId !== source.dataset.taskId && row.dataset.taskId === fresh.dataset.taskId)) return;
      row.replaceWith(fresh);
      fresh.querySelectorAll('.math-content').forEach(renderMathContent);
    });
    document.dispatchEvent(new CustomEvent('worksheet:updated'));
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
    if (root.matches('[data-worksheet-mask]') && root.closest('#ws-items')) {
      try {
        await updateWorksheet(root);
        toast(true, 'Сохранено ✓');
      } catch (error) {
        // Запись уже выполнена: не откатываем переключатель как при ошибке POST.
        toast(false, 'Сохранено, но не удалось обновить вид листка. Обновите страницу.');
      }
    } else update(result, form);
    return result;
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
    var removeSolution=e.target.closest('[data-delete-solution]');
    if(removeSolution){
      if(!confirm('Удалить авторское и редакторское решение? Это действие сохранится сразу.'))return;
      var solutionForm=removeSolution.closest('form');
      ['author_solution_latex','solution_latex'].forEach(function(name){
        var field=solutionForm.querySelector('[name="'+name+'"]');
        if(field)field.value='';
      });
      solutionForm.requestSubmit();return;
    }
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
    var ai=e.target.closest('[data-editor-ai]');if(!ai||ai.disabled)return; // disabled — приглушённая кнопка не-редактора (решение 5)
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
    }catch(error){toast(false,error.message);}finally{ai.disabled=false;var aiMenu=ai.closest('details.ai-menu');if(aiMenu)aiMenu.open=false;}
  });
  // Подсказка на первой открытой общей задаче ([data-shared-task-hint] в
  // _editor.html): показывается, пока учитель её не закрыл; закрытие
  // запоминается в localStorage на этот браузер.
  var HINT_KEY='egormath.sharedTaskHintSeen';
  document.querySelectorAll('[data-shared-task-hint]').forEach(function(hint){
    var seen=false;
    try{seen=localStorage.getItem(HINT_KEY)==='1';}catch(e){}
    if(seen)return;
    hint.hidden=false;
    var close=hint.querySelector('[data-hint-close]');
    if(close)close.addEventListener('click',function(){
      hint.hidden=true;
      try{localStorage.setItem(HINT_KEY,'1');}catch(e){}
    });
  });
  window.EgorProblem={request,endpoint,errors,save,toast};
})();
