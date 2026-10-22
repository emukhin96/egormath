/* Оценки сохраняются отдельно; обновление ответов не трогает комментарии.
   Опрос раз в 5 с: сначала файл-версия страницы (data-live-file, статика без
   Django — см. livefile/files.py), и только при изменении — фрагменты. */
(function(){
  'use strict';
  var dialog=document.getElementById('progress-dialog'), detailUrl=null, busy=false, grading=false, gradeEpoch=0, versions={}, etags={};
  var watch=window.EgorLiveFile?EgorLiveFile.watch(document.querySelector('[data-live-file]')):null, force=false;
  function notify(ok, message) {
    if (dialog && dialog.open) {
      var status = dialog.querySelector('[data-review-status]');
      status.hidden = false; status.textContent = message || 'Сохранено ✓';
      status.className = ok ? 'review-save-success' : 'msg msg-error';
    } else if (window.EgorAutosave) EgorAutosave.showSaved(ok, message);
  }
  async function request(url, options){var r=await fetch(url,options);if(!r.ok && r.status!==304)throw new Error('Не удалось обновить данные');return r;}
  function math(root){if(window.renderMathContent)root.querySelectorAll('.math-content').forEach(renderMathContent);if(window.EgorMask)EgorMask.enhance(root);}
  function replace(root,html){
    var signature=html.replace(/name="csrfmiddlewaretoken" value="[^"]*"/g,'name="csrfmiddlewaretoken"');
    if(root.dataset.previous===signature)return;
    var opened=Array.from(root.querySelectorAll('details')).map(d=>d.open);
    var drafts=Array.from(root.querySelectorAll('[data-preserve-input]')).filter(e=>e.value!==e.defaultValue).map(e=>({name:e.name,value:e.value,start:e.selectionStart,end:e.selectionEnd,focused:e===document.activeElement}));
    root.innerHTML=html;root.dataset.previous=signature;
    drafts.forEach(d=>{var e=Array.from(root.querySelectorAll('[data-preserve-input]')).find(e=>e.name===d.name);if(e){e.value=d.value;if(d.focused){e.focus();e.setSelectionRange(d.start,d.end);}}});
    root.querySelectorAll('details').forEach((d,i)=>{if(i<opened.length)d.open=opened[i];});math(root);
  }
  function updateTable(root, html){
    var parsed=new DOMParser().parseFromString(html,'text/html');
    var oldCells=Array.from(root.querySelectorAll('[data-progress-cell]'));
    var newCells=Array.from(parsed.querySelectorAll('[data-progress-cell]'));
    var oldStructure=Array.from(root.querySelectorAll('[data-progress-structure]')).map(e=>e.dataset.progressStructure).join('|'), newStructure=Array.from(parsed.querySelectorAll('[data-progress-structure]')).map(e=>e.dataset.progressStructure).join('|');
    if(oldStructure!==newStructure || !oldCells.length || oldCells.length!==newCells.length || oldCells.some((c,i)=>c.dataset.progressCell!==newCells[i].dataset.progressCell)){
      var positions=Array.from(root.querySelectorAll('.progress-table-wrap')).map(e=>[e.scrollLeft,e.scrollTop]);
      replace(root,html);root.querySelectorAll('.progress-table-wrap').forEach((e,i)=>{if(positions[i]){e.scrollLeft=positions[i][0];e.scrollTop=positions[i][1];}});return;
    }
    // атрибуты ячейки тоже живые: рамка «решает сейчас», цвет «Сейчас», data-live-until
    oldCells.forEach((cell,i)=>{var fresh=newCells[i];if(cell.outerHTML===fresh.outerHTML)return;
      Array.from(cell.attributes).forEach(a=>{if(!fresh.hasAttribute(a.name))cell.removeAttribute(a.name);});
      Array.from(fresh.attributes).forEach(a=>{if(cell.getAttribute(a.name)!==a.value)cell.setAttribute(a.name,a.value);});
      if(cell.innerHTML!==fresh.innerHTML)cell.innerHTML=fresh.innerHTML;});
  }
  function applyReviewResult(url,result){
    url=new URL(url,location.href).href;
    document.querySelectorAll('[data-grade-url]').forEach(s=>{if(new URL(s.dataset.gradeUrl,location.href).href===url)s.querySelectorAll('[data-grade]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.grade===result.grade)));});
    document.querySelectorAll('[data-review-total-done]').forEach(e=>e.textContent=result.result.done);
    document.querySelectorAll('[data-review-total-percent]').forEach(e=>e.textContent=result.result.percent);
    document.querySelectorAll('[data-point-feedback-url]').forEach(e=>{if(new URL(e.dataset.pointFeedbackUrl,location.href).href===url&&result.feedback!==undefined)e.textContent=result.feedback;});
    document.querySelectorAll('[data-review-pending]').forEach(e=>e.hidden=!result.result.pending);
    document.querySelectorAll('[data-review-pending-count]').forEach(e=>e.textContent=result.result.pending||0);
    if(result.cumulative){document.querySelectorAll('[data-review-cumulative-done]').forEach(e=>e.textContent=result.cumulative.done);document.querySelectorAll('[data-review-cumulative-percent]').forEach(e=>e.textContent=result.cumulative.percent);}
  }
  document.addEventListener('input',function(e){if(e.target.matches('.review-comment textarea'))document.querySelectorAll('.review-comment textarea').forEach(t=>{if(t!==e.target&&t.name===e.target.name)t.value=e.target.value;});});
  document.addEventListener('submit',async function(e){
    var form=e.target.closest('[data-point-review]');if(!form)return;e.preventDefault();
    if(form.dataset.busy)return;form.dataset.busy='1';grading=true;gradeEpoch++;
    try{
      var input=form.querySelector('textarea');if(!input)throw new Error('Не найдено поле комментария');
      var submitted=input.value;
      var result=await (await request(form.action,{method:'POST',body:new FormData(form),headers:{'Accept':'application/json'}})).json();
      applyReviewResult(form.action,result);
      input.defaultValue=submitted;
      notify(true, 'Комментарий сохранён ✓');
    }catch(error){notify(false,error.message);}
    finally{delete form.dataset.busy;grading=false;}
  });
  document.addEventListener('click',async function(e){
    var grade=e.target.closest('[data-grade]'), attempts=e.target.closest('[data-attempt-url]');
    try{
      if(grade){
        var scale=grade.closest('[data-grade-url]');if(scale.dataset.busy)return;scale.dataset.busy='1';grading=true;gradeEpoch++;
        try{
          var data=new FormData();data.set('grade',grade.dataset.grade);data.set('csrfmiddlewaretoken',document.querySelector('[name=csrfmiddlewaretoken]').value);
          var result=await (await request(scale.dataset.gradeUrl,{method:'POST',body:data,headers:{'Accept':'application/json'}})).json();
          applyReviewResult(scale.dataset.gradeUrl,result);
          var caption=scale.parentElement.querySelector('[data-grade-caption]');if(caption)caption.textContent=result.caption||'';
          notify(true, 'Оценка сохранена ✓');
        }finally{delete scale.dataset.busy;grading=false;}
      }
      if(attempts){var requestedUrl=attempts.dataset.attemptUrl;detailUrl=requestedUrl;dialog.querySelector('[data-review-status]').hidden=true;var html=await(await request(requestedUrl)).text();if(detailUrl!==requestedUrl)return;var target=dialog.querySelector('[data-progress-detail]');replace(target,html);if(!dialog.open)dialog.showModal();dialog.scrollTop=0;}
    }catch(error){notify(false,error.message);}
  });
  /* «Проверить как ученик» в окне задачи (_mask_check_form.html): тот же
     task_mask_check, что на карточке задачи. Где загружен редактор масок
     (problem_masks.js, конструктор листка), форму обрабатывает он. Пока
     учитель вводит пробный ответ, окно не перерисовывается опросом. */
  // флажки («решений нет» слота-множества) — по checked: value="1" у них всегда (ревью #276)
  function trialActive(){return Array.from(dialog.querySelectorAll('[data-mask-check] input, [data-mask-check] math-field, [data-mask-check] select')).some(e=>e.type==='checkbox'||e.type==='radio'?e.checked:e.type!=='hidden'&&e.value);}
  document.addEventListener('submit',async function(e){
    var f=e.target.closest('#progress-dialog [data-mask-check]');if(!f||document.getElementById('answer-mask-dialog'))return;e.preventDefault();
    if(f.dataset.busy)return;f.dataset.busy='1';
    var status=f.querySelector('[data-trial-result]');
    try{
      var data=new FormData(f);data.set('csrfmiddlewaretoken',document.querySelector('[name=csrfmiddlewaretoken]').value);
      f.querySelectorAll('math-field[data-mirror]').forEach(function(m){data.set(m.dataset.mirror,(window.EgorMask&&EgorMask.value)?EgorMask.value(m):(m.value||''));});
      var result=await(await fetch(dialog.dataset.maskCheckUrl,{method:'POST',body:data,headers:{'Accept':'application/json'}})).json();
      f.querySelectorAll('[data-check]').forEach(function(h){if(window.EgorCheckBadge)EgorCheckBadge.render(h,'');});
      if(window.EgorCheckBadge)EgorCheckBadge.apply(f,result.checks||{});
      status.textContent=result.message||'';
    }catch(error){status.textContent='Не удалось проверить ответ';}
    finally{delete f.dataset.busy;}
  });
  document.addEventListener('click',function(e){
    var reset=e.target.closest('#progress-dialog [data-mask-reset]');if(!reset||document.getElementById('answer-mask-dialog'))return;var f=reset.closest('[data-mask-check]');
    f.querySelectorAll('math-field[data-mirror]').forEach(function(m){m.value='';});
    f.querySelectorAll('input[type=text],input[type=number]').forEach(function(i){i.value='';});
    f.querySelectorAll('input[type=checkbox]').forEach(function(c){c.checked=false;});
    f.querySelectorAll('select').forEach(function(s){s.value='';});
    f.querySelectorAll('[data-check]').forEach(function(h){if(window.EgorCheckBadge)EgorCheckBadge.render(h,'');});
    f.querySelector('[data-trial-result]').textContent='';
  });
  function stamp(){var status=document.querySelector('[data-live-status]');if(status)status.textContent='Обновлено в '+new Date().toLocaleTimeString();}
  /* Обратный отсчёт самостоятельной считается в браузере (data-remaining-until):
     иначе фрагмент менялся бы каждую секунду и ETag/файл-версия не работали бы.
     Когда время вышло, состояние меняет сервер — просим полный опрос и
     повторяем его, пока сервер не уберёт отсчёт (сбой запроса, расхождение часов). */
  function tickRemaining(){
    var now=Date.now();
    document.querySelectorAll('[data-remaining-until]').forEach(function(el){
      var left=Math.max(0,Math.floor((Date.parse(el.dataset.remainingUntil)-now)/1000));
      if(isNaN(left))return;
      el.textContent=Math.floor(left/60)+':'+String(left%60).padStart(2,'0');
      if(left===0)force=true;
    });
    // «Решает сейчас» гаснет через 15 минут без новых ответов: в БД ничего
    // не меняется, поэтому в момент истечения просим полный опрос
    document.querySelectorAll('[data-live-until]').forEach(function(el){
      var until=Date.parse(el.dataset.liveUntil);if(!isNaN(until)&&now>=until)force=true;
    });
  }
  async function poll(){
    if(document.hidden||busy||grading)return;busy=true;var pollEpoch=gradeEpoch;
    try{
      if(watch&&!force&&!(await watch.changed())){stamp();return;}
      var review=document.querySelector('[data-review-live-url]');
      if(review){var url=new URL(review.dataset.reviewLiveUrl,location.href);url.searchParams.set('versions',JSON.stringify(versions));var data=await(await request(url)).json();versions=data.versions||{};Object.entries(data.rows).forEach(([id,html])=>{document.querySelectorAll('[data-live-answer="'+id+'"]').forEach(root=>replace(root,html));});}
      var table=document.querySelector('[data-progress-overview]')||document.querySelector('[data-progress-table]');
      if(table){var url=new URL(table.dataset.progressUrl||location.href,location.href);url.searchParams.set('fragment','1');var key=url.toString();var response=await request(url,{headers:etags[key]?{'If-None-Match':etags[key]}:{}});if(response.status!==304){var html=await response.text();if(!grading&&pollEpoch===gradeEpoch){updateTable(table,html);etags[key]=response.headers.get('ETag');}}}
      if(dialog&&dialog.open&&detailUrl&&!dialog.querySelector('[data-busy="1"]')&&!trialActive()){
        // Сохраняем выбор оценки при обновлении снимка.
        var polledDetail=detailUrl;var response=await request(polledDetail,{headers:etags[polledDetail]?{'If-None-Match':etags[polledDetail]}:{}});if(response.status!==304){var html=await response.text();if(dialog.open&&detailUrl===polledDetail&&!grading&&pollEpoch===gradeEpoch){replace(dialog.querySelector('[data-progress-detail]'),html);etags[polledDetail]=response.headers.get('ETag');}}
      }
      if(watch)watch.ack();
      force=false;
      stamp();
    }catch(error){var status=document.querySelector('[data-live-status]');if(status)status.textContent='Связь прервана. Повторим обновление автоматически.';}finally{busy=false;}
  }
  if(dialog)dialog.addEventListener('close',function(){detailUrl=null;});
  setInterval(poll,5000);
  setInterval(tickRemaining,1000);tickRemaining();
  document.addEventListener('visibilitychange',function(){if(!document.hidden)poll();});
  poll();
})();
