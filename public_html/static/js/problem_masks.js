/* Один редактор масок для карточки задачи и конструктора листка. */
(function(){
  'use strict';
  var api=window.EgorProblem, active=null, current=null, loading=false, inlineCounter=1000;
  var dialog=document.getElementById('answer-mask-dialog');if(!dialog)return;
  var form=document.getElementById('answer-mask-form');
  var config=document.getElementById('answer-mask-config').dataset;
  var previewDialog=document.getElementById('answer-preview-dialog');
  function body(data){var f=new FormData();Object.entries(data).forEach(p=>f.set(p[0],p[1]));return f;}
  async function answers(root, withPreview){
    var url=new URL(api.endpoint(root),location.href);if(withPreview)url.searchParams.set('preview','1');
    var result=await api.request(url.toString());
    // На карточке генерация учитывает ещё не сохранённый текст выбранного источника.
    if(root.matches('[data-problem-editor]'))result.answers.forEach(function(o){
      var section=root.querySelector('[data-answer-owner="'+(o.id||'')+'"]');
      if(section){o.condition=root.querySelector('[name=text_latex]').value+(o.id?'\n'+o.text:'');o.author=section.querySelector('[name=author_answer_latex]').value;o.editor=section.querySelector('[name=answer_latex]').value;}
    });
    return result.answers;
  }
  function source(){
    var out=form.querySelector('[data-mask-answer]');out.textContent=current[form.elements.source.value]||'Ответ не добавлен';renderMathContent(out);
  }
  function open(root,o){
    active=root;current=o;dialog.querySelector('[data-editor-preview]').hidden=true;dialog.querySelector('[data-editor-preview]').textContent='';form.reset();form.elements.mask.value=o.mask;
    Array.from(form.elements.source.options).forEach(opt=>opt.disabled=!o[opt.value].trim());
    form.elements.source.value=o.author.trim()?'author':'editor';
    form.querySelector('[data-mask-message]').textContent='';form.querySelector('[data-mask-errors]').textContent='';
    document.getElementById('answer-mask-title').textContent='Маска · '+o.label;
    form.elements.reference.value=o[form.elements.source.value]||'';
    source();dialog.showModal();
  }
  async function preview(owners, container){
    var embedded=!!container;container=container||previewDialog.querySelector('[data-preview-body]');container.textContent='';container.hidden=false;
    for(var i=0;i<owners.length;i++){
      var owner=owners[i],prefix='preview_'+i;
      var section=document.createElement('section');section.className='problem-preview-section';
      if(owner.id){var heading=document.createElement('h4');heading.textContent=owner.label;section.appendChild(heading);}
      if(!embedded){var text=document.createElement('div');text.className='math-content';text.textContent=owner.text;section.appendChild(text);renderMathContent(text);}
      if(!owner.mask.trim()){
        var note=document.createElement('p');note.className='helptext';note.textContent='Маски нет — ученик может прислать фото решения.';section.appendChild(note);
      }else{
        var result=await api.request(config.previewUrl,body({mask:owner.mask,prefix}));
        var check=document.createElement('form');check.dataset.maskCheck='1';
        var hidden=document.createElement('input');hidden.type='hidden';hidden.name='mask';hidden.value=owner.mask;check.appendChild(hidden);
        var pref=document.createElement('input');pref.type='hidden';pref.name='prefix';pref.value=prefix;check.appendChild(pref);
        var fields=document.createElement('div');fields.innerHTML=result.html||'';check.appendChild(fields);
        var errors=document.createElement('p');errors.className='errorlist';errors.textContent=(result.errors||[]).join('; ');check.appendChild(errors);
        var button=document.createElement('button');button.className='btn btn-secondary';button.textContent='Проверить пробный ответ';check.appendChild(button);
        var status=document.createElement('p');status.dataset.trialResult='1';status.setAttribute('role','status');check.appendChild(status);
        section.appendChild(check);
        fields.querySelectorAll('.mask-text,.mask-order-items li').forEach(renderMathContent);

      }
      container.appendChild(section);
      if(window.EgorMask)window.EgorMask.enhance(section);
    }
    if(!owners.length)container.textContent='Подпункты не выбраны.';
    if(!embedded)previewDialog.showModal();
  }
  function button(label,key,value){var b=document.createElement('button');b.type='button';b.className='btn btn-small btn-secondary';b.textContent=label;b.dataset[key]=value;return b;}
  async function refresh(root){
    var target=root.querySelector('[data-mask-tools]');if(!target)return;
    target.textContent='Загрузка масок…';
    try{
      var owners=await answers(root,true);target.textContent='';
      var links=root.closest('.ws-item,[data-task-row]')?.querySelector('[data-mask-links]');if(links)links.textContent='';
      var actions=document.createElement('div');actions.className='problem-mask-actions';target.appendChild(actions);
      if(owners.filter(o=>!o.mask.trim()).length>1)actions.appendChild(button('Создать недостающие маски','maskMissing','1'));

      for(var i=0;i<owners.length;i++){
        var o=owners[i],row=document.createElement('div');row.className='problem-mask-summary';
        if(o.id){var title=document.createElement('strong');title.textContent=o.label;row.appendChild(title);}
        if(o.mask){
          var fields=document.createElement('div');fields.className='problem-mask-inline';fields.innerHTML=o.preview_html||'';row.appendChild(fields);
          fields.querySelectorAll('.mask-text,.mask-order-items li').forEach(renderMathContent);
        }
        var editButton=button(o.mask?'Настроить':'Добавить маску','maskEdit',o.id||'');
        if(links){editButton.className='link-btn';editButton.textContent=(o.mask?'настроить маску':'добавить маску')+(o.id?' · '+o.label:'');links.append(editButton,' · ');}else row.appendChild(editButton);
        actions.appendChild(row);
        if(window.EgorMask)window.EgorMask.enhance(row);
      }
    }catch(error){target.textContent=error.message;}
  }
  document.addEventListener('click',async function(e){
    var edit=e.target.closest('[data-mask-edit]'),see=e.target.closest('[data-mask-preview]'),missing=e.target.closest('[data-mask-missing]');
    var trigger=edit||see||missing;if(!trigger||loading)return;
    var root=trigger.closest('[data-problem-editor],[data-worksheet-mask]')||trigger.closest('.ws-item,[data-task-row]')?.querySelector('[data-worksheet-mask]');if(!root)return;
    loading=true;trigger.disabled=true;
    try{
      var owners=await answers(root);
      if(edit){var o=owners.find(o=>String(o.id||'')===edit.dataset.maskEdit);if(o)open(root,o);else throw new Error('Подпункт больше не выбран. Обновите маски.');}
      if(see)await preview(see.dataset.maskPreview==='all'?owners:owners.filter(o=>String(o.id||'')===see.dataset.maskPreview));
      if(missing){
        var changes=[],unresolved=[];
        for(var o of owners.filter(o=>!o.mask.trim())){
          var result=await api.request(config.draftUrl,body({answer:o.author.trim()||o.editor.trim(),condition:o.condition})).catch(()=>({mask:''}));
          if(result.mask)changes.push({id:o.id,mask:result.mask});else unresolved.push(o.label);
        }
        if(unresolved.length)api.toast(false,'Уточните тип вручную: '+unresolved.join(', '));
        if(changes.length){
          // Сначала показываем реальные поля; сохранение — отдельное действие.
          await preview(owners.filter(o=>changes.some(c=>c.id===o.id)).map(o=>({...o,mask:changes.find(c=>c.id===o.id).mask})));
          var save=button('Сохранить созданные маски','saveGenerated','1');
          if(unresolved.length){var note=document.createElement('p');note.className='helptext';note.textContent='Без изменений: '+unresolved.join(', ')+'. Откройте их редакторы и уточните тип.';previewDialog.querySelector('[data-preview-body]').appendChild(note);}
          previewDialog.querySelector('[data-preview-body]').appendChild(save);
          save.addEventListener('click',async()=>{save.disabled=true;try{var result=await api.save(root,body({block:'masks',masks:JSON.stringify(changes),missing_only:'1'}));if(result)previewDialog.close();}catch(error){api.toast(false,error.message);}finally{save.disabled=false;}});
        }
      }
    }catch(error){api.toast(false,error.message);}finally{loading=false;trigger.disabled=false;}
  });
  form.elements.source.addEventListener('change',function(){source();form.elements.reference.value=current[form.elements.source.value]||'';});
  form.querySelector('[data-mask-generate]').addEventListener('click',async function(){
    this.disabled=true;
    try{
      var result=await api.request(config.draftUrl,body({answer:current[form.elements.source.value]||'',condition:current.condition}));
      if(form.elements.mask.value.trim()&&!confirm('Заменить текущую маску новым черновиком?'))return;
      form.elements.mask.value=result.mask;form.querySelector('[data-mask-message]').textContent='Черновик готов. Проверьте предпросмотр перед сохранением.';
    }catch(error){form.querySelector('[data-mask-message]').textContent=error.message;form.querySelector('.problem-section').open=true;}
    finally{this.disabled=false;}
  });
  form.querySelectorAll('[data-mask-template]').forEach(function(b){b.addEventListener('click',function(){
    var field=form.elements.mask, snippet='{{number: '+b.dataset.maskTemplate+'}}';
    field.setRangeText(snippet,field.selectionStart,field.selectionEnd,'select');field.focus();
    form.querySelector('[data-mask-message]').textContent='Вставлен пример. Укажите правильное значение вместо него.';
  });});
  form.querySelector('[data-mask-insert]').addEventListener('click',function(){
    form.elements.mask.value+=(form.elements.mask.value?' ':'')+form.elements.prefix.value+' {{'+form.elements.kind.value+': '+form.elements.reference.value+'}}';
  });
  form.querySelector('[data-mask-try]').addEventListener('click',async()=>{try{await preview([{...current,mask:form.elements.mask.value}],dialog.querySelector('[data-editor-preview]'));}catch(error){api.toast(false,error.message);}});
  form.addEventListener('submit',async function(e){
    e.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';e.submitter.disabled=true;
    try{
      var result=await api.save(active,body({block:'masks',masks:JSON.stringify([{id:current.id,mask:form.elements.mask.value}])}));
      if(result)dialog.close();
    }catch(error){api.errors(form.querySelector('[data-mask-errors]'),error);}
    finally{delete form.dataset.busy;e.submitter.disabled=false;}
  });
  document.addEventListener('submit',async function(e){
    var f=e.target.closest('[data-mask-check]');if(!f)return;e.preventDefault();
    try{
      var data=new FormData(f);f.querySelectorAll('math-field[data-mirror]').forEach(m=>data.set(m.dataset.mirror,m.value||''));
      var result=await api.request(config.previewUrl,data);
      if(window.EgorCheckBadge)window.EgorCheckBadge.apply(f,result.checks||{});
      f.querySelector('[data-trial-result]').textContent=({ok:'Верно',wrong:'Неверно',unknown:'Не все поля заполнены или ответ не разобран'})[result.overall]||'Введите пробный ответ';
    }catch(error){f.querySelector('[data-trial-result]').textContent=error.message;}
  });
  var toggle=document.getElementById('toggle-masks');
  if(toggle){
    try{toggle.checked=sessionStorage.getItem(toggle.dataset.storageKey||'worksheet-masks')==='1';}catch(_){}
    function display(){
      try{sessionStorage.setItem(toggle.dataset.storageKey||'worksheet-masks',toggle.checked?'1':'0');}catch(_){}
      document.querySelectorAll('[data-worksheet-mask]').forEach(function(root){root.hidden=!toggle.checked;if(toggle.checked)refresh(root);});
    }
    toggle.addEventListener('change',display);display();
    document.addEventListener('autosave:done',function(e){
      if(!toggle.checked || !e.detail.ok)return;
      var row=e.target.closest('.ws-item');
      var root=row && row.querySelector('[data-worksheet-mask]');
      if(root)refresh(root);
    });
  }
})();
