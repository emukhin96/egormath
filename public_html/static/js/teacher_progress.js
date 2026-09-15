/* Оценки сохраняются отдельно; обновление ответов не трогает комментарии. */
(function(){
  'use strict';
  var dialog=document.getElementById('progress-dialog'), detailUrl=null, busy=false, grading=false, gradeEpoch=0, versions={}, etags={};
  async function request(url, options){var r=await fetch(url,options);if(!r.ok && r.status!==304)throw new Error('Не удалось обновить данные');return r;}
  function math(root){if(window.renderMathContent)root.querySelectorAll('.math-content').forEach(renderMathContent);}
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
    oldCells.forEach((cell,i)=>{if(cell.innerHTML!==newCells[i].innerHTML)cell.innerHTML=newCells[i].innerHTML;});
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
      if(window.EgorAutosave)EgorAutosave.showSaved(true);
    }catch(error){if(window.EgorAutosave)EgorAutosave.showSaved(false,error.message);}
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
          if(window.EgorAutosave)EgorAutosave.showSaved(true);
        }finally{delete scale.dataset.busy;grading=false;}
      }
      if(attempts){var requestedUrl=attempts.dataset.attemptUrl;detailUrl=requestedUrl;var html=await(await request(requestedUrl)).text();if(detailUrl!==requestedUrl)return;var target=dialog.querySelector('[data-progress-detail]');replace(target,html);dialog.showModal();}
    }catch(error){if(window.EgorAutosave)EgorAutosave.showSaved(false,error.message);}
  });
  async function poll(){
    if(document.hidden||busy||grading)return;busy=true;var pollEpoch=gradeEpoch;
    try{
      var review=document.querySelector('[data-review-live-url]');
      if(review){var url=new URL(review.dataset.reviewLiveUrl,location.href);url.searchParams.set('versions',JSON.stringify(versions));var data=await(await request(url)).json();versions=data.versions||{};Object.entries(data.rows).forEach(([id,html])=>{document.querySelectorAll('[data-live-answer="'+id+'"]').forEach(root=>replace(root,html));});}
      var table=document.querySelector('[data-progress-overview]')||document.querySelector('[data-progress-table]');
      if(table){var url=new URL(table.dataset.progressUrl||location.href,location.href);url.searchParams.set('fragment','1');var key=url.toString();var response=await request(url,{headers:etags[key]?{'If-None-Match':etags[key]}:{}});if(response.status!==304){var html=await response.text();if(!grading&&pollEpoch===gradeEpoch){updateTable(table,html);etags[key]=response.headers.get('ETag');}}}
      if(dialog&&dialog.open&&detailUrl&&!dialog.querySelector('[data-busy="1"]')){
        // Сохраняем выбор оценки при обновлении снимка.
        var polledDetail=detailUrl;var response=await request(polledDetail,{headers:etags[polledDetail]?{'If-None-Match':etags[polledDetail]}:{}});if(response.status!==304){var html=await response.text();if(dialog.open&&detailUrl===polledDetail&&!grading&&pollEpoch===gradeEpoch){replace(dialog.querySelector('[data-progress-detail]'),html);etags[polledDetail]=response.headers.get('ETag');}}
      }
      var status=document.querySelector('[data-live-status]');if(status)status.textContent='Обновлено '+new Date().toLocaleTimeString()+'. Нажмите ячейку для ответов и попыток.';
    }catch(error){var status=document.querySelector('[data-live-status]');if(status)status.textContent='Связь прервана. Повторим обновление автоматически.';}finally{busy=false;}
  }
  if(dialog)dialog.addEventListener('close',function(){detailUrl=null;});
  setInterval(poll,5000);
  document.addEventListener('visibilitychange',function(){if(!document.hidden)poll();});
  poll();
})();
