/* A live diagram of server-reported retrieval stages. */
(() => {
  const panel=document.getElementById('stage-retrieval');
  const graph=document.createElement('section'); graph.id='retrieval-flow'; graph.hidden=true;
  graph.setAttribute('aria-label','Retrieval information flow'); graph.setAttribute('aria-live','polite');
  graph.innerHTML='<h3><button type="button" class="flow-collapse-toggle" aria-expanded="true" aria-controls="retrieval-flow-canvas"><span aria-hidden="true" class="flow-collapse-chevron">▾</span>Retrieval flow</button></h3><p class="flow-caption"></p><div class="flow-grid"></div>';
  const timingPanel=document.getElementById('progress');
  panel.insertBefore(graph,timingPanel);
  const conditions=document.getElementById('retrieval-overview-disclosure');if(conditions)graph.after(conditions);
  const timingDisclosure=document.createElement('details');timingDisclosure.className='retrieval-timing-disclosure';timingDisclosure.hidden=true;
  const timingSummary=document.createElement('summary');timingSummary.textContent='Detailed retrieval timings';timingDisclosure.append(timingSummary);timingPanel.before(timingDisclosure);timingDisclosure.append(timingPanel);
  const grid=graph.querySelector('.flow-grid');grid.id='retrieval-flow-canvas';const viewport=document.createElement('div');viewport.className='flow-viewport';viewport.setAttribute('role','region');viewport.setAttribute('aria-label','Retrieval data flow');viewport.tabIndex=0;grid.before(viewport);viewport.append(grid);
  const collapse=graph.querySelector('.flow-collapse-toggle');collapse.addEventListener('click',()=>{const open=collapse.getAttribute('aria-expanded')!=='true';collapse.setAttribute('aria-expanded',String(open));graph.classList.toggle('flow-collapsed',!open);queueDraw();});
  let mode='hybrid',execution='parallel',statisticsEvent=null,selectedPlan=false,needsRelaxation=false;
  const nodes={};
  for(const [key,label,position] of [['bm25','BM25 retrieval','branch-bm25'],['bm25-output','BM25 candidates','output-bm25'],['vector','Vector retrieval','branch-vector'],['vector-output','Vector candidates','output-vector'],['fallback','Relax required logic','fallback-node'],['retry','BM25 retry','retry-node'],['retry-output','Retry candidates','retry-output'],['rrf','RRF fusion','fusion-node'],['output','Fusion output','fusion-output']]) {
    const node=document.createElement('div'); node.className='flow-node '+position; node.dataset.state='waiting';
    const title=document.createElement('strong');title.textContent=label;
    const value=document.createElement('span');value.textContent='Waiting';
    node.append(title,value);grid.append(node);nodes[key]=node;
  }
  for(const key of ['fallback','retry','retry-output'])nodes[key].hidden=true;
  const inspector=document.createElement('section');inspector.className='query-inspector';inspector.hidden=true;
  inspector.innerHTML='<div class="query-inspector-header"><h4></h4><div><button type="button" data-branch="bm25">BM25</button><button type="button" data-branch="vector">Vector</button><button type="button" data-close aria-label="Close query inspector">×</button></div></div><div class="query-inspector-tools"><div role="tablist" aria-label="Query view"><button type="button" role="tab" data-view="overview">Overview</button><button type="button" role="tab" data-view="dsl">Raw DSL</button></div><select aria-label="Executed request attempt"></select><button type="button" data-copy>Copy full DSL</button></div><p class="query-inspector-status" role="status"></p><div class="query-overview"></div><details class="query-vector"><summary>Query vector</summary><pre></pre></details><pre class="query-dsl" tabindex="0"></pre>';
  graph.append(inspector);
  let queryData=null, selectedBranch='bm25', selectedAttempt=0, selectedView='overview';
  const codeIcon='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16"/></svg>';
  for(const key of ['bm25','vector','retry']){
    const button=document.createElement('button');button.type='button';button.className='query-inspect-trigger';button.innerHTML=codeIcon;button.setAttribute('aria-label','Inspect '+key+' executed query');button.title='Inspect executed query';
    button.addEventListener('click',()=>{selectedBranch=key==='vector'?'vector':'bm25';selectedAttempt=key==='retry'?1:0;inspector.hidden=false;renderInspector();});nodes[key].append(button);
  }
  function renderInspector(){
    const traces=queryData?.executed_queries?.[selectedBranch]||[];selectedAttempt=Math.min(selectedAttempt,Math.max(0,traces.length-1));const trace=traces[selectedAttempt];
    inspector.querySelector('h4').textContent=selectedBranch.toUpperCase()+' · Executed query';
    for(const key of ['bm25','vector','retry'])nodes[key].classList.toggle('query-selected',!inspector.hidden&&key===(selectedBranch==='vector'?'vector':selectedAttempt?'retry':'bm25'));
    inspector.querySelectorAll('[data-branch]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.branch===selectedBranch)));
    inspector.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===selectedView)));
    const select=inspector.querySelector('select');select.replaceChildren();traces.forEach((t,i)=>{const option=document.createElement('option');option.value=i;option.textContent=({initial:'Original required groups',any_required:'Any required ingredient',no_required:'No required ingredient',retry:'Relaxed retry'})[t.attempt]||t.attempt;select.append(option);});select.value=selectedAttempt;select.hidden=traces.length<2;
    const status=inspector.querySelector('.query-inspector-status');
    const level=queryData?.bm25_fallback?.levels?.find(l=>l.stage===(trace?.attempt==='initial'?'original':trace?.attempt));
    status.textContent=trace?`${level?(level.used?'Used in merged recall':'No unique candidates added'):'Executed request'} · Actual backend snapshot${trace.error_type?' · Failed: '+trace.error_type:''}`:(queryData?'No executed query snapshot available. Run retrieval with the updated backend.':'Request snapshot will be available when retrieval finishes.');
    inspector.querySelector('[data-copy]').disabled=!trace;
    const overview=inspector.querySelector('.query-overview');overview.replaceChildren();overview.hidden=selectedView!=='overview';
    const pre=inspector.querySelector('.query-dsl');pre.hidden=selectedView!=='dsl';
    const vectorDetails=inspector.querySelector('.query-vector');vectorDetails.hidden=true;
    if(!trace){pre.textContent='';return;}
    const settings=trace.settings||{},body=trace.body,knn=body.knn;
    const rows=[['Recall strategy',settings.retrieval_strategy||'text'],['Text matching',selectedBranch==='vector'?'Semantic embedding':settings.retrieval_strategy==='label_scope'?'Skipped':(settings.bm25_query ?? settings.query)],['Semantic query',trace.semantic_query],['Vector scope query',trace.semantic_scope_query],['Scope weight β',trace.vector_scope_weight],['Meal boost',settings.bm25_meal_type],['Cuisine target',settings.cuisine_target],['Cuisine role',settings.cuisine_role],['Required logic',globalThis.RecipeRequired?.format(settings.required_expression)||'Any included ingredient'],['Must include',(settings.include_ingredients||[]).join(', ')],['Must exclude',(settings.exclude_ingredients||[]).join(', ')],['Manual labels',(settings.labels||[]).join(', ')],['Numeric filters',JSON.stringify(settings.numeric_filters||[])],['Max total time',settings.max_total_time_minutes],['Max calories',settings.max_calories],['Candidate limit',body.size],['Available ingredients',(settings.preference_available||[]).join(', ')],['Available boost',selectedBranch==='bm25'?settings.bm25_available_boost:'Not used'],['Vector field',knn?.field],['k',knn?.k],['Exploration candidates',knn?.num_candidates]];
    const dl=document.createElement('dl');for(const [label,value]of rows){if(value===undefined||value===null)continue;const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=String(value||'None');dl.append(dt,dd);}overview.append(dl);
    for(const [label,value]of [['Applied filtering',body.query?.bool?.filter||knn?.filter||null],['Ranking clauses',body.query?.bool?.should||[]]]){const details=document.createElement('details'),summary=document.createElement('summary'),code=document.createElement('pre');summary.textContent=label;code.textContent=JSON.stringify(value,null,2);details.append(summary,code);overview.append(details);}
    const copy=JSON.parse(JSON.stringify(body));if(knn?.query_vector){copy.knn.query_vector='['+knn.query_vector.length+' dimensions · expand Query vector below]';vectorDetails.hidden=selectedView!=='dsl';vectorDetails.querySelector('summary').textContent='Query vector · '+knn.query_vector.length+' dimensions';vectorDetails.querySelector('pre').textContent=JSON.stringify(knn.query_vector);}
    pre.textContent=JSON.stringify(copy,null,2);
  }
  inspector.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-close')){inspector.hidden=true;renderInspector();}if(b.dataset.branch){selectedBranch=b.dataset.branch;selectedAttempt=0;renderInspector();}if(b.dataset.view){selectedView=b.dataset.view;renderInspector();}if(b.hasAttribute('data-copy')){try{await navigator.clipboard.writeText(JSON.stringify(queryData.executed_queries[selectedBranch][selectedAttempt].body,null,2));inspector.querySelector('.query-inspector-status').textContent='Full DSL copied, including the query vector.';}catch{inspector.querySelector('.query-inspector-status').textContent='Copy unavailable. Select and copy the Raw DSL text.';}}});
  inspector.querySelector('[role=tablist]').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();selectedView=e.key==='Home'?'overview':e.key==='End'?'dsl':selectedView==='overview'?'dsl':'overview';renderInspector();inspector.querySelector('[data-view='+selectedView+']').focus();});
  inspector.querySelector('select').addEventListener('change',e=>{selectedAttempt=Number(e.target.value);renderInspector();});
  const constraints=document.createElement('small'); constraints.className='flow-constraints';nodes.bm25.append(constraints);
  const scopeInfo=document.createElement('p');scopeInfo.className='field-help';scopeInfo.hidden=true;graph.querySelector('.flow-caption').after(scopeInfo);
  function showScope(strategy,meal=[],cuisine=[]) {
    const active=strategy==='label_scope';
    scopeInfo.hidden=!active;
    scopeInfo.textContent=active?`Both branches require label scope: ${meal.length?'Meal '+meal.join(' / '):''}${meal.length&&cuisine.length?' AND ':''}${cuisine.length?'Cuisine '+cuisine.join(' / '):''}. BM25 skips content matching; Vector uses the semantic query.`:'';
    nodes.bm25.querySelector('strong').textContent=active?'BM25 · label scope':'BM25 retrieval';
    nodes.retry.querySelector('strong').textContent='BM25 supplemental recall';
  }
  for(const [key,title] of [['preparing','Preparing retrieval'],['strict-check','Strict candidate check'],['decision','Relaxation decision'],['relaxed-bm25','Relaxed BM25'],['relaxed-vector','Relaxed Vector'],['relaxed-bm25-output','Relaxed BM25 candidates'],['relaxed-vector-output','Relaxed Vector candidates'],['merged','Strict-first merge']]){
    const node=document.createElement('div');node.className='flow-node unified-'+key;node.dataset.state='waiting';node.hidden=true;
    const heading=document.createElement('strong');heading.textContent=title;const value=document.createElement('span');value.textContent='Waiting';node.append(heading,value);grid.append(node);nodes[key]=node;
  }
  // Keep screen-reader and keyboard order aligned with the top-to-bottom diagram.
  for(const key of ['preparing','bm25','bm25-output','vector','vector-output','strict-check','decision','fallback','retry','retry-output','relaxed-bm25','relaxed-bm25-output','relaxed-vector','relaxed-vector-output','merged','rrf','output'])grid.append(nodes[key]);
  const outputKeys=new Set(['bm25-output','vector-output','retry-output','relaxed-bm25-output','relaxed-vector-output']);
  for(const [key,node] of Object.entries(nodes)){
    node.querySelector('span').classList.add('flow-value');
    if(outputKeys.has(key)){node.classList.add('flow-output');continue;}
    const marker=document.createElement('span');marker.className='flow-step-state';marker.setAttribute('aria-hidden','true');node.append(marker);
  }
  // Templates remain detached. Cards and branch slots enter the live DOM only
  // when an actual running/completed event reaches that stage.
  for(const node of Object.values(nodes))node.remove();
  const cards=new Map();
  const stageOrder={prepare:0,strict:10,candidate_check:15,decision:20,additional:30,fusion:40,output:50};
  function stageFor(key){return key==='strict-check'?'candidate_check':key==='preparing'?'prepare':key==='decision'||key==='fallback'?'decision':key.startsWith('relaxed-')||key.startsWith('retry')?'additional':key==='merged'||key==='rrf'?'fusion':key==='output'?'output':'strict';}
  function mountNode(key){
    const stage=stageFor(key);let card=cards.get(stage);
    if(!card){
      card=document.createElement('section');card.className='flow-stage-card';card.dataset.stage=stage;
      if(['strict','additional'].includes(stage)){
        const header=document.createElement('div');header.className='flow-stage-header';
        const heading=document.createElement('h4');heading.textContent=stage==='strict'?'Initial retrieval':'Additional retrieval';
        const badge=document.createElement('span');badge.className='flow-execution-label';badge.textContent=mode==='hybrid'?(execution==='serial'?'Sequential':'Parallel'):'Single branch';header.append(heading,badge);card.append(header);
      }
      const body=document.createElement('div');body.className='flow-stage-body';card.append(body);
      cards.set(stage,card);const next=[...grid.querySelectorAll(':scope > .flow-stage-card')].find(c=>stageOrder[c.dataset.stage]>stageOrder[stage]);grid.insertBefore(card,next||null);
    }
    const body=card.querySelector('.flow-stage-body'),node=nodes[key];
    let branch=key.includes('vector')?'vector':key.includes('bm25')||key.startsWith('retry')?'bm25':null;
    if(['strict','additional'].includes(stage)&&branch){
      let slot=body.querySelector('[data-branch-slot='+branch+']');
      if(!slot){slot=document.createElement('div');slot.className='flow-branch-slot';slot.dataset.branchSlot=branch;const firstVector=body.querySelector('[data-branch-slot=vector]');body.insertBefore(slot,branch==='bm25'?firstVector:body.querySelector('.unified-strict-check'));}
      if(node.parentElement!==slot){if(outputKeys.has(key))slot.append(node);else slot.prepend(node);}
    }else if(node.parentElement!==body){if(key==='merged')body.prepend(node);else body.append(node);}
  }
  function pruneCards(){for(const [key,card] of cards){if(!card.querySelector('.flow-node:not([hidden])')){card.remove();cards.delete(key);}}}
  const relaxationPanel=document.createElement('section');relaxationPanel.className='relaxation-inspector';relaxationPanel.id='relaxation-inspector';relaxationPanel.hidden=true;relaxationPanel.setAttribute('aria-label','Recall relaxation decision');graph.append(relaxationPanel);
  const inspectRelaxation=document.createElement('button');inspectRelaxation.type='button';inspectRelaxation.disabled=true;inspectRelaxation.className='decision-inspect-icon';inspectRelaxation.title='Inspect relaxation decision';inspectRelaxation.setAttribute('aria-label','Inspect relaxation decision');inspectRelaxation.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/><circle cx="10" cy="18" r="2" fill="currentColor"/></svg>';inspectRelaxation.setAttribute('aria-expanded','false');inspectRelaxation.setAttribute('aria-controls',relaxationPanel.id);nodes.decision.append(inspectRelaxation);
  for(const branch of ['bm25','vector']){
    const button=document.createElement('button');button.type='button';button.className='query-inspect-trigger';button.innerHTML=codeIcon;button.setAttribute('aria-label','Inspect relaxed '+branch+' executed query');
    button.addEventListener('click',()=>{selectedBranch=branch;selectedAttempt=Math.max(0,(queryData?.executed_queries?.[branch]||[]).length-1);inspector.hidden=false;renderInspector();});nodes['relaxed-'+branch].append(button);
  }
  inspectRelaxation.addEventListener('click',()=>{relaxationPanel.hidden=!relaxationPanel.hidden;inspectRelaxation.setAttribute('aria-expanded',String(!relaxationPanel.hidden));});
  function relaxationDetails(data){
    const r=data.relaxation;if(!r)return;graph.classList.toggle('has-relaxed-recall',Boolean(r.selected_plan));graph.classList.add('unified-relaxation');graph.classList.remove('has-fallback');
    for(const key of ['fallback','retry','retry-output'])nodes[key].hidden=true;
    
    set('strict-check',`${r.strict_candidate_count} unique strict candidates · threshold ${r.threshold}${r.status==='strict_sufficient'?' · No relaxation needed':''}`);
    if(r.status!=='strict_sufficient')set('decision',({strict_sufficient:'Strict candidates sufficient',no_plan:'No relaxation · no plan reaches target',statistics_failed:'Statistics failed · strict retained',complete:'Recall conditions relaxed',partial:'Partial recall · successes retained',failed:'Relaxed recall failed · strict retained'})[r.status]||r.status,['failed','statistics_failed'].includes(r.status)?'failed':'complete');
    for(const branch of ['bm25','vector']){
      for(const key of ['relaxed-'+branch,'relaxed-'+branch+'-output'])nodes[key].hidden=!r.selected_plan||!enabled(branch);
      if(!enabled(branch))continue;
      const run=r.executions?.[branch];
      if(run){set('relaxed-'+branch,ms(run.elapsed_ms),run.status);set('relaxed-'+branch+'-output',`${run.returned} returned · ${run.added} new`,run.status);}
      if(r.selected_plan&&run?.status!=='complete')nodes['relaxed-'+branch].dataset.state='failed';
    }
    for(const branch of ['bm25','vector'])if(enabled(branch)&&r.strict_branches?.[branch]){const b=r.strict_branches[branch];set(branch,ms(b.elapsed_ms),b.status);set(branch+'-output',`${b.returned} strict candidates`,b.status);}
    inspectRelaxation.disabled=false;
    set('merged',`${data.candidate_counts.union} unique · strict first`);
    relaxationPanel.replaceChildren();
    const el=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
    relaxationPanel.append(el('h4','Recall relaxation decision'),el('p',`${r.strict_candidate_count} unique strict candidates / threshold ${r.threshold}. Filter-range target ${r.relaxed_candidates}. Statistics: ${r.statistics?.status||'Not needed'} · ${ms(r.statistics?.elapsed_ms)}.`));
    relaxationPanel.append(el('p','Filter-range counts do not include text matching. They are not actual BM25 or Vector recall counts.'));
    if(r.statistics?.missing_numeric&&Object.keys(r.statistics.missing_numeric).length)relaxationPanel.append(el('p','Missing numeric values under original non-numeric filters: '+Object.entries(r.statistics.missing_numeric).map(([k,v])=>k+': '+v).join(' · ')+'. Missing values cannot establish final eligibility.'));
    const protectedText=(r.protected_conditions||[]).map(c=>`${c.name}: ${c.sole_core_exception?'Core · sole required filter may relax for recall':c.protected?'Core · protected':c.reason}`).join(' · ');
    if(protectedText)relaxationPanel.append(el('p',protectedText));
    const scroll=el('div','');scroll.className='relaxation-table-scroll';const table=el('table','');table.append(el('caption','Candidate relaxation plans'));
    const head=el('tr','');for(const name of ['Plan / condition changes','Filter matches','Added matches','Cost','Decision'])head.append(el('th',name));table.append(head);
    const strict=el('tr','');for(const value of ['Original conditions',r.statistics?.counts?.strict??'Unavailable','—','0','Original qualification requirements remain unchanged'])strict.append(el('td',String(value)));table.append(strict);
    for(const plan of r.plans||[]){
      const row=el('tr','');row.dataset.selected=String(Boolean(plan.selected));
      const actionText=plan.actions.map(a=>a.type==='drop_ingredient'?`Remove required ${a.value}`:`${a.field}: ${a.from.map(c=>c.operator+' '+c.value).join(' AND ')} → ${a.to.length?a.to.map(c=>c.operator+' '+(a.field==='total_time'?Math.ceil(c.value):Number(c.value.toFixed(3)))).join(' AND '):'No recall limit'}`).join('; ');
      for(const value of [actionText,plan.filter_match_count??r.statistics?.counts?.[plan.plan_id]??'Unavailable',plan.additional_filter_matches??'—',plan.cost,plan.selected?'Selected · '+plan.reason:plan.reason||'Not needed'])row.append(el('td',String(value)));table.append(row);
    }
    scroll.append(table);relaxationPanel.append(scroll);
    const json=el('details','');json.append(el('summary','Execution snapshots & statistics DSL'));const pre=el('pre',JSON.stringify(r,null,2));const copy=el('button','Copy decision JSON');copy.type='button';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(pre.textContent);copy.textContent='Copied';}catch{copy.textContent='Copy unavailable';}});json.append(copy,pre);relaxationPanel.append(json);
    for(const branch of ['bm25','vector'])if(r.executions?.[branch])relaxationPanel.append(el('p',`${branch.toUpperCase()}: ${r.executions[branch].returned} actually returned · ${r.executions[branch].added} new versus strict · ${ms(r.executions[branch].elapsed_ms)} · ${r.executions[branch].status}`));
    queueDraw();
  }
  const retryConstraints=document.createElement('small');retryConstraints.className='flow-constraints';retryConstraints.textContent='Required-only relaxation. Excluded and other hard filters retained.';nodes.retry.append(retryConstraints);
  function showFallback(){graph.classList.add('has-fallback');for(const key of ['fallback','retry','retry-output'])nodes[key].hidden=false;}
  const ns='http://www.w3.org/2000/svg';
  const links=document.createElementNS(ns,'svg');links.classList.add('flow-links');links.setAttribute('aria-hidden','true');links.setAttribute('focusable','false');grid.prepend(links);
  const defs=document.createElementNS(ns,'defs');
  for(const [id,color] of [['flow-arrow','#246347'],['flow-arrow-muted','#a4b3aa']]){
    const marker=document.createElementNS(ns,'marker');marker.id=id;marker.setAttribute('viewBox','0 0 10 10');marker.setAttribute('refX','8');marker.setAttribute('refY','5');marker.setAttribute('markerWidth','6');marker.setAttribute('markerHeight','6');marker.setAttribute('orient','auto');
    const tip=document.createElementNS(ns,'path');tip.setAttribute('d','M1 1 8 5 1 9');tip.setAttribute('fill','none');tip.setAttribute('stroke',color);tip.setAttribute('stroke-width','1.5');marker.append(tip);defs.append(marker);
  }
  let frame=0;
  function draw(){
    frame=0;
    if(graph.hidden)return;
    const box=grid.getBoundingClientRect(); if(!box.width||!box.height)return;
    links.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);links.replaceChildren(defs);
    const steps=[...grid.querySelectorAll(':scope > .flow-stage-card')].filter(card=>getComputedStyle(card).display!=='none');
    const horizontal=window.matchMedia('(min-width: 761px)').matches;
    const edge=(source,target)=>{
      const a=source.getBoundingClientRect(),b=target.getBoundingClientRect();
      let d;
      if(horizontal){const x1=a.right-box.left+2,x2=b.left-box.left-3,y1=a.top+a.height/2-box.top,y2=b.top+b.height/2-box.top;if(x2<=x1)return;const mid=(x1+x2)/2;d=`M${x1} ${y1} H${mid} V${y2} H${x2}`;}
      else{const x=a.left+a.width/2-box.left,y1=a.bottom-box.top+2,y2=b.top-box.top-3;if(y2<=y1)return;d=`M${x} ${y1} V${y2}`;}
      const group=document.createElementNS(ns,'g');
      group.dataset.flow=target.querySelector('[data-state=failed],[data-state=timeout]')?'failed':target.querySelector('[data-state=running]')&&graph.dataset.phase==='running'?'running':'complete';
      for(const cls of ['flow-wire','flow-particles']){const path=document.createElementNS(ns,'path');path.setAttribute('d',d);path.setAttribute('class',cls);if(cls==='flow-wire')path.setAttribute('marker-end','url(#flow-arrow)');group.append(path);}links.append(group);
    };
    for(let i=1;i<steps.length;i++){
      const source=steps[i-1],target=steps[i];
      const sourceBranches=source.querySelectorAll('.flow-branch-slot'),targetBranches=target.querySelectorAll('.flow-branch-slot');
      if(horizontal&&sourceBranches.length){for(const branch of sourceBranches)edge(branch,target);}
      else if(horizontal&&targetBranches.length){for(const branch of targetBranches)edge(source,branch);}
      else edge(source,target);
    }
  }

  function queueDraw(){if(!frame)frame=requestAnimationFrame(draw);}
  new ResizeObserver(queueDraw).observe(grid);
  let onScreen=true;const motionState=()=>graph.dataset.motionActive=String(onScreen&&!document.hidden);
  new IntersectionObserver(entries=>{onScreen=entries[0].isIntersecting;motionState();}).observe(graph);
  document.addEventListener('visibilitychange',motionState);
  const markerIcons={running:'<circle cx="12" cy="12" r="8" stroke-opacity=".25"/><path d="M12 4a8 8 0 0 1 8 8"/>',complete:'<path d="m7 12 3 3 7-7"/>',failed:'<path d="m8 8 8 8m0-8-8 8"/>',timeout:'<path d="M12 7v6m0 3v1"/>'};
  const set=(key,value,state='complete')=>{
    const node=nodes[key];node.querySelector('.flow-value').textContent=value;node.dataset.state=state;
    node.setAttribute('role','group');node.setAttribute('aria-label',node.querySelector('strong').textContent+' · '+state+' · '+value);
    node.setAttribute('aria-busy',String(state==='running'));
    if(!['waiting','skipped'].includes(state)){node.hidden=false;node.dataset.entered='true';mountNode(key);pruneCards();}
    const marker=node.querySelector('.flow-step-state');
    if(marker)marker.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">'+(markerIcons[state]||'<circle cx="12" cy="12" r="3"/>')+'</svg>';
    const button=node.querySelector('.query-inspect-trigger');if(button)button.disabled=!queryData;
    queueDraw();
  };
  function resetNodes(){for(const card of cards.values())card.remove();cards.clear();for(const [key,node] of Object.entries(nodes)){node.remove();node.hidden=true;node.removeAttribute('data-entered');set(key,'Waiting','waiting');}statisticsEvent=null;selectedPlan=false;needsRelaxation=false;}
  const ms=value=>typeof value==='number'&&Number.isFinite(value)?(value<1000?value.toFixed(2)+' ms':(value/1000).toFixed(2)+' s'):'Time unavailable';
  const enabled=step=>mode==='hybrid'||step===mode;
  globalThis.RecipeRetrievalFlow={
    clear(){timingDisclosure.hidden=true;timingDisclosure.open=false;graph.querySelector('.flow-level-details')?.remove();queryData=null;inspector.hidden=true;relaxationPanel.hidden=true;inspectRelaxation.setAttribute('aria-expanded','false');inspectRelaxation.disabled=true;graph.classList.remove('unified-relaxation','has-relaxed-recall','has-fallback');resetNodes();graph.hidden=true;graph.dataset.phase='idle';if(frame)cancelAnimationFrame(frame);frame=0;},
    start(selected,filters={}){
      this.clear();mode=selected;execution=filters.execution||'parallel';
      graph.hidden=false;graph.dataset.phase='running';timingDisclosure.hidden=false;
      showScope(filters.strategy,filters.meal,filters.cuisine);
      constraints.textContent=`Required: ${globalThis.RecipeRequired?.format(filters.expression)||((filters.include||[]).length?'any of '+filters.include.join(', '):'None')} · Exclude: ${(filters.exclude||[]).join(', ')||'None'}`;
      graph.querySelector('.flow-caption').title='Rows show execution progress; parallel branches can run at the same time. Timings are reported by the backend.';
      graph.querySelector('.flow-caption').textContent=(mode==='hybrid'?(execution==='serial'?'Sequential branches':'Parallel branches'):'Single branch')+' · Live backend progress';
      nodes.output.querySelector('strong').textContent=mode==='hybrid'?'Fusion output':'Retrieval output';
      set('preparing','Connecting to retrieval…','running');
    },
    update(event){
      if(graph.dataset.phase==='idle'||graph.hidden)return;
      if(event.step==='relaxation_statistics'){
        statisticsEvent=event;
        if(needsRelaxation&&!nodes['strict-check'].hidden&&nodes.decision.hidden)set('decision','Evaluating recall conditions…','running');
        return;
      }
      if(event.step==='strict_candidate_check'){
        graph.classList.add('unified-relaxation');
        needsRelaxation=event.threshold>0&&event.candidate_count<event.threshold;
        set('strict-check',`${event.candidate_count} strict candidates · threshold ${event.threshold}${needsRelaxation?'':' · No relaxation needed'}`);
        if(needsRelaxation&&statisticsEvent)set('decision','Evaluating recall conditions…','running');
        return;
      }
      if(event.step==='relaxation_decision'){
        if(event.status==='strict_sufficient')return;
        graph.classList.add('unified-relaxation');selectedPlan=selectedPlan||Boolean(event.plan);
        const text=event.plan?'Plan selected · additional recall':({strict_sufficient:'Strict candidates sufficient',no_plan:'No relaxation · no plan reaches target',statistics_failed:'Statistics unavailable · strict retained',complete:selectedPlan?'Relaxed recall complete':'Decision complete',partial:'Partial recall · successes retained',failed:'Relaxed recall failed · strict retained'})[event.status]||'Evaluating recall conditions…';
        set('decision',text,['failed','statistics_failed'].includes(event.status)?'failed':event.status==='running'?'running':'complete');return;
      }
      if(event.step==='candidate_merge'){set('merged',`${event.candidate_count} unique · strict first`);return;}
      if(['bm25_fallback','bm25_retry'].includes(event.step))return;
      const key=({bm25_initial:'bm25',bm25_retry:'retry',relaxed_bm25:'relaxed-bm25',relaxed_vector:'relaxed-vector'})[event.step]||event.step;
      if(!nodes[key]||['waiting','skipped'].includes(event.status))return;
      if(['bm25','vector'].includes(key)&&!enabled(key))return;
      if(['bm25','vector','retry','relaxed-bm25','relaxed-vector'].includes(key)){
        nodes.preparing.dataset.state='complete';nodes.preparing.setAttribute('aria-busy','false');nodes.preparing.querySelector('.flow-value').textContent='Connected';nodes.preparing.hidden=true;
        if(key.startsWith('relaxed-'))graph.classList.add('has-relaxed-recall');
        const state=event.status;
        set(key,state==='running'?'Retrieving…':state==='complete'?ms(event.elapsed_ms):state==='timeout'?'Timed out':'Retrieval failed',state);
        if(Number.isInteger(event.candidate_count))set(key+'-output',`${event.candidate_count} ${key.startsWith('relaxed-')?'returned':'recipes'}${Number.isInteger(event.added)?' · '+event.added+' new':''}`,state);
        else if(['failed','timeout'].includes(state))set(key+'-output','No usable candidates',state);
        return;
      }
      if(key==='rrf'){
        if(mode!=='hybrid')return;
        set('rrf',event.status==='running'?'Fusing candidates…':ms(event.elapsed_ms),event.status);
        if(event.status==='complete'&&Number.isInteger(event.candidate_count))set('output',`${event.candidate_count} unique candidates · preparing results…`,'running');
      }
    },
    complete(data){
      queryData=data;nodes.preparing.dataset.state='complete';nodes.preparing.setAttribute('aria-busy','false');nodes.preparing.querySelector('.flow-value').textContent='Connected';nodes.preparing.hidden=true;if(!inspector.hidden)renderInspector();
      showScope(data.retrieval_strategy,data.effective_filters?.scope_meal_types,data.effective_filters?.scope_cuisines);
      graph.dataset.phase='complete';
      for(const step of ['bm25','vector']){
        const branch=data.branches?.[step];
        if(branch)this.update({step,...branch});
        if(enabled(step)) {
          const count=data.candidate_counts?.[step] ?? branch?.candidate_count ?? (data.mode===step?data.results.length:null);
          set(step+'-output',count==null?'Count unavailable':`${count} recipes`,branch?.status||'complete');
        }
      }
      const fallback=data.bm25_fallback;
      const original=data.original_conditions||data.relaxation?.original_conditions;
      if(original)constraints.textContent=`Required: ${globalThis.RecipeRequired?.format(original.required_expression)||((original.include_ingredients||[]).length?'any of '+original.include_ingredients.join(', '):'None')} · Exclude: ${(original.exclude_ingredients||[]).join(', ')||'None'}`;

      if(mode==='hybrid'){
        set('rrf',ms(data.timings?.rrf_ms),'complete');
        const count=data.candidate_counts?.rrf ?? data.candidate_counts?.union;
        set('output',`${count==null?'Count unavailable':count+' unique candidates'} · ${data.results.length} displayed`);
      }else set('output',data.results.length+' recipes displayed');
      relaxationDetails(data);
      graph.querySelector('.flow-caption').title='Backend timings · Vector includes query embedding. '+(mode==='hybrid'?'Fusion output is before preference reranking and display truncation. Strict results are retained ahead of relaxed results. Original ingredient requirements remain binding in Recipe Check.':'Single-branch retrieval; RRF is not used.')+(fallback?.used?' BM25 retains strict candidates and supplements them through required-only relaxation; exclusions remain enforced.':'')+(data.mode==='hybrid'&&data.effective_mode!=='hybrid'?' Degraded retrieval: only '+data.effective_mode.toUpperCase()+' succeeded.':'');
      graph.querySelector('.flow-caption').textContent=(mode==='hybrid'?(data.execution==='serial'?'Sequential branches':'Parallel branches'):'Single branch')+' · Backend timings'+(data.mode==='hybrid'&&data.effective_mode!=='hybrid'?' · Degraded: '+data.effective_mode.toUpperCase()+' only':'');
    },
    fail(){graph.dataset.phase='failed';graph.querySelector('.flow-caption').textContent='Retrieval interrupted · completed steps retained';queueDraw();for(const [key,node]of Object.entries(nodes))if(!node.hidden&&node.dataset.state==='running')set(key,'Failed · retry retrieval','failed');}
  };
})();
