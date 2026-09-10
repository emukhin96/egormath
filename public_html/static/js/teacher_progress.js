/* Оценки сохраняются отдельно; обновление ответов не трогает комментарии. */
(function(){
  'use strict';
  var dialog=document.getElementById('progress-dialog'), detailUrl=null, busy=false, grading=false, gradeEpoch=0, versions={}, etags={};
  async function request(url, options){var r=await fetch(url,options);if(!r.ok && r.status!==304)throw new Error('Не удалось обновить данные');return r;}
  function math(root){if(window.renderMathContent)root.querySelectorAll('.math-content').forEach(renderMathContent);}
  function replace(root,html){
    if(root.dataset.previous===html)return;
    var opened=Array.from(root.querySelectorAll('details')).map(d=>d.open);
    root.innerHTML=html;root.dataset.previous=html;
    root.querySelectorAll('details').forEach((d,i)=>{if(i<opened.length)d.open=opened[i];});math(root);
  }
  function updateTable(root, html){
    var parsed=new DOMParser().parseFromString(html,'text/html');
    var oldCells=Array.from(root.querySelectorAll('[data-progress-cell]'));
    var newCells=Array.from(parsed.querySelectorAll('[data-progress-cell]'));
    var oldStructure=root.querySelector('[data-progress-structure]'), newStructure=parsed.querySelector('[data-progress-structure]');
    if(oldStructure?.dataset.progressStructure!==newStructure?.dataset.progressStructure || !oldCells.length || oldCells.length!==newCells.length || oldCells.some((c,i)=>c.dataset.progressCell!==newCells[i].dataset.progressCell)){
      var scroller=root.querySelector('.progress-table-wrap'), left=scroller?.scrollLeft||0, top=scroller?.scrollTop||0;
      replace(root,html);var next=root.querySelector('.progress-table-wrap');if(next){next.scrollLeft=left;next.scrollTop=top;}return;
    }
    oldCells.forEach((cell,i)=>{if(cell.innerHTML!==newCells[i].innerHTML)cell.innerHTML=newCells[i].innerHTML;});
  }
  document.addEventListener('input',function(e){if(e.target.matches('.review-comment textarea'))document.querySelectorAll('.review-comment textarea').forEach(t=>{if(t!==e.target&&t.name===e.target.name)t.value=e.target.value;});});
  document.addEventListener('click',async function(e){
    var grade=e.target.closest('[data-grade]'), attempts=e.target.closest('[data-attempt-url]');
    try{
      if(grade){
        var scale=grade.closest('[data-grade-url]');if(scale.dataset.busy)return;scale.dataset.busy='1';grading=true;gradeEpoch++;
        try{
          var data=new FormData();data.set('grade',grade.dataset.grade);data.set('csrfmiddlewaretoken',document.querySelector('[name=csrfmiddlewaretoken]').value);
          var result=await (await request(scale.dataset.gradeUrl,{method:'POST',body:data})).json();
          document.querySelectorAll('[data-grade-url]').forEach(s=>{if(s.dataset.gradeUrl===scale.dataset.gradeUrl)s.querySelectorAll('[data-grade]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.grade===result.grade)));});
          document.querySelectorAll('[data-review-total-done]').forEach(e=>e.textContent=result.result.done);
          document.querySelectorAll('[data-review-total-percent]').forEach(e=>e.textContent=result.result.percent);
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
      var table=document.querySelector('[data-progress-table]');
      if(table){var url=new URL(location.href);url.searchParams.set('fragment','1');var key=url.toString();var response=await request(url,{headers:etags[key]?{'If-None-Match':etags[key]}:{}});if(response.status!==304){var html=await response.text();if(!grading&&pollEpoch===gradeEpoch){updateTable(table,html);etags[key]=response.headers.get('ETag');}}}
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
