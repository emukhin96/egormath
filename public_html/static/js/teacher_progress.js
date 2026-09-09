/* Оценки сохраняются отдельно; обновление ответов не трогает комментарии. */
(function(){
  'use strict';
  var dialog=document.getElementById('progress-dialog'), detailUrl=null, busy=false;
  async function request(url, options){var r=await fetch(url,options);if(!r.ok)throw new Error('Не удалось обновить данные');return r;}
  function math(root){if(window.renderMathContent)root.querySelectorAll('.math-content').forEach(renderMathContent);}
  function replace(root,html){
    if(root.dataset.previous===html)return;
    var opened=Array.from(root.querySelectorAll('details')).map(d=>d.open);
    root.innerHTML=html;root.dataset.previous=html;
    root.querySelectorAll('details').forEach((d,i)=>{if(i<opened.length)d.open=opened[i];});math(root);
  }
  document.addEventListener('click',async function(e){
    var grade=e.target.closest('[data-grade]'), attempts=e.target.closest('[data-attempt-url]');
    try{
      if(grade){
        var scale=grade.closest('[data-grade-url]');if(scale.dataset.busy)return;scale.dataset.busy='1';
        try{
          var data=new FormData();data.set('grade',grade.dataset.grade);data.set('csrfmiddlewaretoken',document.querySelector('[name=csrfmiddlewaretoken]').value);
          var result=await (await request(scale.dataset.gradeUrl,{method:'POST',body:data})).json();
          scale.querySelectorAll('[data-grade]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.grade===result.grade)));
          document.querySelectorAll('[data-review-total-done]').forEach(e=>e.textContent=result.result.done);
          document.querySelectorAll('[data-review-total-percent]').forEach(e=>e.textContent=result.result.percent);
          if(window.EgorAutosave)EgorAutosave.showSaved(true);
        }finally{delete scale.dataset.busy;}
      }
      if(attempts){detailUrl=attempts.dataset.attemptUrl;var html=await(await request(detailUrl)).text();var target=dialog.querySelector('[data-progress-detail]');replace(target,html);dialog.showModal();}
    }catch(error){if(window.EgorAutosave)EgorAutosave.showSaved(false,error.message);}
  });
  async function poll(){
    if(document.hidden||busy)return;busy=true;
    try{
      var review=document.querySelector('[data-review-live-url]');
      if(review){var data=await(await request(review.dataset.reviewLiveUrl)).json();Object.entries(data.rows).forEach(([id,html])=>{var root=document.querySelector('[data-live-answer="'+id+'"]');if(root)replace(root,html);});}
      var table=document.querySelector('[data-progress-table]');
      if(table){var url=new URL(location.href);url.searchParams.set('fragment','1');replace(table,await(await request(url)).text());}
      if(dialog&&dialog.open&&detailUrl&&!dialog.querySelector('[data-busy="1"]')){
        // Сохраняем выбор оценки при обновлении снимка.
        replace(dialog.querySelector('[data-progress-detail]'),await(await request(detailUrl)).text());
      }
      var status=document.querySelector('[data-live-status]');if(status)status.textContent='Обновлено '+new Date().toLocaleTimeString()+'. Нажмите ячейку для ответов и попыток.';
    }catch(error){var status=document.querySelector('[data-live-status]');if(status)status.textContent='Связь прервана. Повторим обновление автоматически.';}finally{busy=false;}
  }
  setInterval(poll,5000);
})();
