(function () {
  'use strict';
  document.addEventListener('submit', async event => {
    const form=event.target;
    if (!form.classList.contains('metrology-redo-form') && !form.classList.contains('metrology-ignore-form') && !form.classList.contains('metrology-restore-form')) return;
    event.preventDefault();
    const ignore=form.classList.contains('metrology-ignore-form');
    const restore=form.classList.contains('metrology-restore-form');
    if (ignore && (!window.confirm('Ignore this measurement? It will be excluded from scores and graphs.') ||
        !window.confirm('Confirm again: ignore this measurement? This action is recorded.'))) return;
    const button=form.querySelector('button');
    if (button.disabled) return;
    button.disabled=true;
    const old=button.textContent; button.textContent=ignore?'Ignoring…':(restore?'Restoring…':'Queuing…');
    try {
      const response=await fetch(form.action,{method:'POST',body:new FormData(form),credentials:'same-origin',headers:{'Accept':'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('The action could not be completed.');
      const result=await response.json();
      if (ignore || restore) { window.location.reload(); return; }
      if (!['queued','already_queued'].includes(result.status)) throw new Error('Unexpected response.');
      document.querySelectorAll('.metrology-redo-form').forEach(other=>{
        if (other.dataset.fileset===form.dataset.fileset) { const b=other.querySelector('button'); b.textContent='Queued'; b.disabled=true; }
      });
    } catch (error) { button.disabled=false; button.textContent=old; window.alert(error.message || 'The action could not be completed.'); }
  });
}());
