(function () {
  'use strict';
  const root = document.getElementById('metrology-drilldown');
  if (!root) return;
  const parse = id => JSON.parse(document.getElementById(id).textContent);
  const lensHistory = parse('lens-history-data'), categoryHistory = parse('category-history-data'), lenses = parse('lens-data');
  const lensChoice = document.getElementById('lens-choice'), categoryChoice = document.getElementById('category-choice');
  const lensChart = document.getElementById('lens-chart'), categoryChart = document.getElementById('category-chart');
  const lensDetail = document.getElementById('lens-detail'), categoryDetail = document.getElementById('category-detail');
  const detailStatus = document.getElementById('detail-status'), figureStatus = document.getElementById('figure-status');
  const charts = document.getElementById('measurement-charts'), gallery = document.getElementById('figure-gallery');
  let rows = [], serial = 0;
  const escapeText = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function layout(title, score) {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {autosize:true, xaxis:{title:{text:'Date'}, type:'date'}, yaxis:{title:{text:escapeText(title)}, automargin:true, ...(score ? {range:[0,1.05]} : {})},
      margin:{l:65,r:20,t:25,b:65}, paper_bgcolor:'transparent', plot_bgcolor:'transparent', font:{color:dark?'#e5e7eb':'#243247'}, legend:{orientation:'h'}};
  }
  function plot(target, traces, title, score, click) {
    if (!window.Plotly) { target.textContent = 'The interactive graph could not be loaded.'; return; }
    Plotly.react(target, traces, layout(title, score), {responsive:true, displaylogo:false}).then(() => {
      target.removeAllListeners('plotly_click');
      if (click) target.on('plotly_click', event => click(event.points[0].customdata));
    });
  }
  function series(items, key, label) {
    const groups = new Map();
    items.forEach(item => { const id=String(item[key]); if (!groups.has(id)) groups.set(id,{name:escapeText(label(id)), x:[], y:[], customdata:[], mode:'lines+markers', type:'scatter'});
      const trace=groups.get(id); trace.x.push(item.day); trace.y.push(item.score); trace.customdata.push(id); });
    return Array.from(groups.values());
  }
  const lensName = id => { const l=lenses.find(x=>String(x.id)===id); return l ? `${l.magnification || 'Lens'}${l.numerical_aperture == null ? '' : ', NA '+l.numerical_aperture}${l.immersion ? ', '+l.immersion : ''}` : id; };
  lensHistory.sort((a,b)=>a.day.localeCompare(b.day));
  categoryHistory.sort((a,b)=>a.day.localeCompare(b.day));
  plot(lensChart, series(lensHistory,'lens_id',lensName),'Score',true,id=>{lensChoice.value=id; selectLens();});
  document.getElementById('score-toggle').addEventListener('click', event => {
    const panel=document.getElementById('score-table'); panel.hidden=!panel.hidden;
    event.currentTarget.setAttribute('aria-expanded',String(!panel.hidden)); event.currentTarget.textContent=panel.hidden?'Show score table':'Hide score table';
  });
  function filterScores() {
    document.querySelectorAll('.metrology-score-row').forEach(row => { row.hidden=!!lensChoice.value && row.dataset.lens!==lensChoice.value; });
    document.querySelectorAll('.score-detail-row').forEach(row=>row.remove());
    document.querySelectorAll('.score-details-button').forEach(button=>button.setAttribute('aria-expanded','false'));
  }
  function actionForm(url, label, className, key) {
    const token=document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (!url || !token) return null;
    const form=document.createElement('form'); form.method='post'; form.action=url; form.className=className;
    if (key) form.dataset.fileset=key;
    const input=document.createElement('input'); input.type='hidden'; input.name='csrfmiddlewaretoken'; input.value=token.value;
    const button=document.createElement('button'); button.type='submit'; button.className='button is-small is-light'; button.textContent=label;
    form.append(input,button); return form;
  }
  document.getElementById('score-table').addEventListener('click', async event => {
    const button=event.target.closest('.score-details-button'); if (!button) return;
    const parent=button.closest('tr');
    const existing=parent.nextElementSibling;
    if (existing && existing.classList.contains('score-detail-row')) { existing.remove(); button.setAttribute('aria-expanded','false'); return; }
    const detail=document.createElement('tr'); detail.className='score-detail-row';
    const cell=document.createElement('td'); cell.colSpan=7; cell.textContent='Loading details…'; detail.append(cell); parent.after(detail); button.setAttribute('aria-expanded','true');
    try {
      const url=new URL(root.dataset.scoreDetails,location.href);
      url.searchParams.set('lens',button.dataset.lens); url.searchParams.set('category',button.dataset.category); url.searchParams.set('day',button.dataset.day);
      const response=await fetch(url,{credentials:'same-origin'}); if (!response.ok) throw new Error();
      const data=await response.json(); if (!detail.isConnected) return;
      cell.replaceChildren();
      if (!data.measurements.length) {cell.textContent='No measurements available for this score.'; return;}
      const groups=new Map();
      data.measurements.forEach(item=>{
        const key=JSON.stringify([item.run_id,item.image_id,item.artifact_id]);
        if (!groups.has(key)) groups.set(key,[]); groups.get(key).push(item);
      });
      groups.forEach(items=>{
        const first=items[0], section=document.createElement('div'); section.className='box';
        const title=document.createElement('p'); title.textContent=`Fileset ${first.fileset_id} · Image ${first.image_id || 'unknown'}`; section.append(title);
        if (first.omero_url) {const link=document.createElement('a'); link.href=first.omero_url; link.target='_blank'; link.rel='noopener noreferrer'; link.textContent='Open in OMERO'; section.append(link);}
        if (first.figure_url) {const link=document.createElement('a'), img=document.createElement('img'); link.href=first.figure_url; link.target='_blank'; link.rel='noopener noreferrer'; img.src=first.figure_url; img.alt=`${button.dataset.category} analysis figure`; img.loading='lazy'; img.style.maxWidth='min(100%, 700px)'; img.style.display='block'; link.append(img); section.append(link);}
        else {const note=document.createElement('p'); note.textContent='No displayable figure for this result.'; section.append(note);}
        items.forEach(item=>{const line=document.createElement('div'); line.className='metrology-controls'; const text=document.createElement('span'); text.textContent=`${item.measurement_type}: ${item.value} ${item.unit || ''} · ${item.status}`; line.append(text);
          if (item.ignore_url && !['ignore','ignored'].includes(item.status.toLowerCase())) {const form=actionForm(item.ignore_url,'Ignore measurement','metrology-ignore-form'); if(form) line.append(form);}
          section.append(line);
        });
        if (first.redo_url) {if (['pending','running'].includes(first.redo_state)) {const note=document.createElement('p'); note.textContent='REDO '+first.redo_state; section.append(note);}
          else {const form=actionForm(first.redo_url,'Queue fileset REDO','metrology-redo-form',`${first.source}:${first.fileset_id}`); if(form) section.append(form);}}
        cell.append(section);
      });
    } catch (_) {if(detail.isConnected) cell.textContent='Unable to load score details.';}
  });
  function selectLens() {
    filterScores();
    serial++; categoryDetail.hidden=true; const lens=lensChoice.value; lensDetail.hidden=!lens;
    categoryChoice.replaceChildren(new Option('Select a category',''));
    if (!lens) return;
    const categories=Array.from(new Set(rows.filter(r=>String(r.lens_id)===lens).map(r=>r.category))).sort();
    categories.forEach(category=>categoryChoice.add(new Option(category,category)));
    const history=categoryHistory.filter(r=>String(r.lens_id)===lens);
    plot(categoryChart,series(history,'category',x=>x),'Score',true,category=>{categoryChoice.value=category; selectCategory();});
  }
  function selectCategory() {
    const token=++serial, lens=lensChoice.value, category=categoryChoice.value;
    categoryDetail.hidden=!category; charts.replaceChildren(); gallery.replaceChildren(); if (!category) return;
    document.getElementById('category-title').textContent=category+' measurements';
    const selected=rows.filter(r=>String(r.lens_id)===lens && r.category===category);
    const metrics=new Map();
    selected.forEach(row=>{const key=JSON.stringify([row.measurement_type,row.unit||'']); if(!metrics.has(key)) metrics.set(key,[]); metrics.get(key).push(row);});
    detailStatus.textContent=metrics.size ? 'Hover for details. Dates use acquisition time, or import time when missing.' : 'No dated measurements for this selection.';
    metrics.forEach((items,key)=>{
      const [name,unit]=JSON.parse(key), div=document.createElement('div'); div.style.minHeight='300px'; charts.append(div);
      const trace={name:escapeText(name),x:items.map(x=>x.measured_at),y:items.map(x=>x.value),mode:'lines+markers',type:'scatter',
        text:items.map(x=>escapeText(x.status+' · '+(x.has_acquisition_time?'acquisition':'import'))),hovertemplate:'%{x}<br>%{y}<br>%{text}<extra>%{fullData.name}</extra>'};
      plot(div,[trace],name+(unit?' ('+unit+')':''),false);
    });
    figureStatus.textContent='Loading figures…';
    const url=new URL(root.dataset.figures,window.location.href); url.searchParams.set('lens',lens); url.searchParams.set('category',category);
    fetch(url,{credentials:'same-origin'}).then(r=>{if(!r.ok) throw Error(); return r.json();}).then(data=>{
      if(token!==serial) return; figureStatus.textContent=data.figures.length ? 'Figures produced by the analysis (up to 36 most recent).' : 'No displayable analysis figures for this category.';
      data.figures.forEach(item=>{const a=document.createElement('a'),img=document.createElement('img'); a.href=item.url; a.target='_blank'; a.rel='noopener noreferrer'; img.src=item.url; img.loading='lazy'; img.alt='Analysis figure for OMERO image '+item.image_id; a.append(img); gallery.append(a);});
    }).catch(()=>{if(token===serial) figureStatus.textContent='Figures could not be loaded.';});
  }
  lensChoice.addEventListener('change',selectLens); categoryChoice.addEventListener('change',selectCategory);
  fetch(root.dataset.history,{credentials:'same-origin'}).then(r=>{if(!r.ok) throw Error(); return r.json();}).then(data=>{ rows=data.measurements; selectLens(); if(data.truncated) detailStatus.textContent='Showing the most recent 5,000 measurements.'; }).catch(()=>{detailStatus.textContent='Measurement history could not be loaded.';});
}());

