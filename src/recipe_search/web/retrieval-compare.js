/* A frozen, in-memory baseline; comparison never issues retrieval requests. */
(() => {
  const host=document.createElement('section');host.className='retrieval-comparison';host.setAttribute('aria-label','Compare retrieval runs');
  document.getElementById('retrieval-research-details').append(host);
  let current=null,savedBaseline=null;
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const label=mode=>({bm25:'BM25',vector:'Vector',hybrid:'Hybrid · RRF'}[mode]||mode);
  const id=r=>String(r.recipe_id);
  const latency=s=>{const t=s.data.timings||{};const n=t.search_total_ms??t[s.body.mode+'_recall_ms'];return Number.isFinite(n)?`${n.toFixed(1)} ms${s.data.from_hybrid_run?' branch only':''}`:'Timing unavailable';};
  const snapshot=record=>({data:structuredClone(record.data),body:structuredClone(record.body),saved:new Date().toLocaleTimeString()});
  function action(text,fn){const b=node('button',text);b.type='button';b.addEventListener('click',fn);return b;}
  function render(){
    host.replaceChildren();
    const strict=current?.data.relaxation_baseline;
    const automatic=Boolean(strict);
    const baseline=automatic?{body:current.body,data:{...current.data,results:strict.results,candidate_counts:{[current.body.mode]:strict.candidate_count},timings:{[current.body.mode+'_recall_ms']:strict.elapsed_ms},from_hybrid_run:current.data.from_hybrid_run},saved:'Before relaxation'}:savedBaseline;
    const bar=node('div',undefined,'comparison-toolbar');
    const heading=node('div');heading.append(node('h3','Compare runs'),node('p',automatic?`Strict baseline · ${label(current.body.mode)} · saved automatically before supplemental recall`:baseline?`Baseline saved at ${baseline.saved} · ${label(baseline.body.mode)}`:'Save a result, change parameters, then refresh to compare.','field-help'));
    const save=action(baseline?'Replace baseline':'Save as baseline',()=>{savedBaseline=snapshot(current);render();});save.disabled=!current;
    bar.append(heading,save);if(automatic)save.hidden=true;if(baseline&&!automatic)bar.append(action('Clear baseline',()=>{savedBaseline=null;render();}));host.append(bar);
    if(!baseline)return;
    host.append(node('p',automatic?'Before: original strict recall. After: strict results retained plus supplemental recall, deduplicated. Each branch keeps its own baseline; counts below compare displayed recipes.':'Saved in this page only. Reloading clears the baseline. Comparisons use displayed recipes, not the full candidate pool.','field-help'));
    if(!current){host.append(node('p','Baseline kept. Run retrieval to compare it with a fresh result.','field-help'));return;}
    const old=baseline.data.results||[],fresh=current.data.results||[];
    const oldRanks=new Map(old.map((r,i)=>[id(r),i+1])),newRanks=new Map(fresh.map((r,i)=>[id(r),i+1]));
    const common=fresh.filter(r=>oldRanks.has(id(r))).length;
    host.append(node('p',`${common} shared · ${fresh.length-common} new in current · ${old.length-common} absent from current`,'comparison-totals'));
    if(baseline.body.mode!==current.body.mode)host.append(node('p','Different retrieval modes: raw scores are not directly comparable. Rank changes refer to these displayed lists.','field-help'));
    const settings=node('details');settings.className='comparison-parameters';settings.append(node('summary','Parameter changes'));
    const keys=[...new Set([...Object.keys(baseline.body),...Object.keys(current.body)])].filter(k=>JSON.stringify(baseline.body[k])!==JSON.stringify(current.body[k]));
    settings.firstChild.textContent=`Parameter changes (${keys.length})`;settings.open=keys.length>0;
    if(automatic){settings.firstChild.textContent='Recall conditions relaxed';settings.open=true;for(const action of current.data.relaxation?.selected_plan?.actions||[])settings.append(node('p',action.type==='drop_ingredient'?`Remove required ${action.value} for supplemental recall only`:`Relax ${action.field}: ${JSON.stringify(action.from)} → ${JSON.stringify(action.to)}`,'field-help'));}
    else if(!keys.length)settings.append(node('p','Same execution parameters.','field-help'));
    else {const table=node('table');const tr=node('tr');['Parameter','Saved','Current'].forEach(t=>tr.append(node('th',t)));table.append(tr);for(const key of keys){const row=node('tr');[key,JSON.stringify(baseline.body[key])??'—',JSON.stringify(current.body[key])??'—'].forEach(t=>row.append(node('td',t)));table.append(row);}settings.append(table);}host.append(settings);
    const columns=node('div',undefined,'comparison-columns');
    for(const [s,rows,other,isNew] of [[baseline,old,newRanks,false],[current,fresh,oldRanks,true]]){
      const col=node('section',undefined,'comparison-column');col.append(node('h4',`${automatic?(isNew?'After supplemental recall':'Before relaxation'):(isNew?'Current':'Saved')} · ${label(s.body.mode)}`),node('p',`${rows.length} shown${automatic?' / '+(s.data.candidate_counts?.[s.body.mode]??rows.length)+' candidates':''} · ${latency(s)}`,'field-help'));
      const query=s.body.mode==='vector'?s.body.vector_query:s.body.bm25_query||s.body.query;col.append(node('p',query||'No query','comparison-query'));
      const list=node('ol');for(const [i,r] of rows.entries()){
        const li=node('li');li.append(node('strong',r.name||`Recipe ${id(r)}`),node('span',`Recipe ID: ${id(r)}`,'comparison-recipe-id'));
        let movement=other.has(id(r))?(isNew?other.get(id(r))-(i+1):(i+1)-other.get(id(r))):null;
        const text=movement===null?(isNew?'New':'Absent from current'):movement===0?'Same rank':`${movement>0?'↑':'↓'} ${Math.abs(movement)} ${isNew?'vs saved':'in current'}`;
        li.append(node('span',text,'comparison-movement'));list.append(li);
      }col.append(list);columns.append(col);
    }host.append(columns);
  }
  document.addEventListener('retrieval-view-updated',event=>{const r=event.detail;current=r.status==='ready'?r:null;render();});
  render();
})();
