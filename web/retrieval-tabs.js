/* Independent branch workbenches over the same edited constraints. */
(() => {
  const form=document.getElementById('search-form'), stage=document.getElementById('stage-retrieval');
  const modeInput=document.getElementById('mode'), config=document.getElementById('retrieval-configuration');
  const resultList=document.getElementById('results'), empty=document.getElementById('empty');
  const modes=['bm25','vector','hybrid'];
  const state=Object.fromEntries(modes.map(mode=>[mode,{data:null,body:null,status:'empty',message:''}]));
  let active='hybrid',busy=false;
  const tabs=document.createElement('div');tabs.className='retrieval-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Retrieval branches');
  const workspace=document.createElement('section');workspace.id='retrieval-workbench';workspace.setAttribute('role','tabpanel');workspace.tabIndex=0;
  const intro=document.createElement('div');intro.className='retrieval-tab-intro';
  const title=document.createElement('h3'),description=document.createElement('p');description.className='field-help';intro.append(title,description);
  const grid=document.createElement('div');grid.className='branch-parameter-grid';workspace.append(intro,grid);
  const status=document.createElement('p');status.id='retrieval-tab-status';workspace.setAttribute('aria-describedby',status.id);status.className='retrieval-tab-status';status.setAttribute('role','status');workspace.append(status);
  config.querySelector(':scope > summary').textContent='Shared constraints & recommendation preferences';
  config.before(tabs);config.after(workspace);
  const modeLabel=modeInput.closest('label');modeLabel.hidden=true;modeLabel.parentElement.hidden=true;
  const flow=document.getElementById('retrieval-flow');
  const flowDisclosure=document.createElement('details');flowDisclosure.id='branch-flow-details';
  const flowSummary=document.createElement('summary');flowSummary.textContent='Executed retrieval flow & DSL';flowDisclosure.append(flowSummary);flow.before(flowDisclosure);flowDisclosure.append(flow);
  const buttons={};
  for(const key of modes){
    const button=document.createElement('button');button.type='button';button.id='retrieval-tab-'+key;button.setAttribute('role','tab');button.setAttribute('aria-controls',workspace.id);button.dataset.retrievalTab=key;
    const name=document.createElement('strong');name.textContent=key==='hybrid'?'Hybrid · RRF':key==='bm25'?'BM25':'Vector';
    const detail=document.createElement('span');button.append(name,detail);button.addEventListener('click',()=>select(key));tabs.append(button);buttons[key]=button;
  }
  tabs.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const index=modes.indexOf(event.target.closest('[role=tab]')?.dataset.retrievalTab||active),next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;
    select(modes[next]);buttons[modes[next]].focus();
  });
  function card(key,label,help){
    const section=document.createElement('section');section.className='branch-parameter-card retrieval-settings';section.dataset.parameterBranch=key;
    const h=document.createElement('h4');h.textContent=label;const p=document.createElement('p');p.className='field-help';p.textContent=help;section.append(h,p);grid.append(section);return section;
  }
  const cards={
    bm25:card('bm25','BM25 recall','Lexical matches and boosts. The list keeps branch recall order, including strict and relaxed recall provenance.'),
    vector:card('vector','Vector recall','Main meaning + weighted scope. The list keeps the semantic branch order before fusion.'),
    hybrid:card('hybrid','Fusion & output','Refresh runs both branches with their current fields, then computes RRF and the enabled preference reranking.')
  };
  const wrapper=id=>document.getElementById(id).closest('label');
  cards.bm25.append(wrapper('query'),document.getElementById('bm25-dish-name').closest('details'));
  const bmSettings=document.createElement('div');bmSettings.className='controls';cards.bm25.append(bmSettings);
  for(const id of ['bm25-candidates'])bmSettings.append(wrapper(id));
  const relaxationSettings=document.createElement('details');relaxationSettings.className='relaxation-settings';const relaxationSummary=document.createElement('summary');relaxationSummary.textContent='Recall relaxation';relaxationSettings.append(relaxationSummary);const relaxationControls=document.createElement('div');relaxationControls.className='controls';for(const id of ['bm25-fallback-threshold','relaxed-candidates','near-miss-target'])relaxationControls.append(wrapper(id));relaxationSettings.append(relaxationControls);config.append(relaxationSettings);
  cards.vector.append(wrapper('vector-query'),wrapper('vector-scope-query').parentElement);
  const vectorSettings=document.createElement('div');vectorSettings.className='controls';cards.vector.append(vectorSettings);
  for(const id of ['vector-candidates','vector-num-candidates'])vectorSettings.append(wrapper(id));
  const fusionSettings=document.createElement('div');fusionSettings.className='controls';cards.hybrid.append(fusionSettings);
  for(const id of ['execution','rrf-k','bm25-boost','vector-boost'])fusionSettings.append(wrapper(id));
  cards.hybrid.classList.add('fusion-parameter-card');
  // Shared output count applies to all three views, so it has a single source of truth.
  const output=document.createElement('div');output.className='retrieval-output-controls';output.append(wrapper('size'));intro.append(output);
  const originalSettings=config.querySelector('.retrieval-settings:not(#preference-settings)');
  const help=document.getElementById('retrieval-help');if(help)cards.hybrid.append(help);
  if(originalSettings)originalSettings.remove();
  const parameters=document.createElement('details');parameters.id='retrieval-parameters';parameters.className='retrieval-parameters';parameters.open=false;
  const parametersSummary=document.createElement('summary');parametersSummary.textContent='Retrieval parameters · edit queries and settings';parameters.append(parametersSummary);
  config.before(parameters);parameters.append(workspace);
  const research=document.createElement('details');research.id='retrieval-research-details';
  const researchSummary=document.createElement('summary');researchSummary.textContent='Research details · parameters & comparison';research.append(researchSummary);
  // Keep the execution flow above results, with secondary diagnostics below.
  form.append(flowDisclosure,resultList,research);research.append(parameters);
  for(const id of ['progress','retrieval-overview-disclosure']){const el=document.getElementById(id);if(el)research.append(id==='progress'?(el.closest('.retrieval-timing-disclosure')||el):el);}
  const preferences=document.getElementById('preference-settings');if(preferences)parameters.append(preferences);
  parameters.append(relaxationSettings);
  const refreshRow=document.createElement('div');refreshRow.className='retrieval-refresh-bottom';
  const refresh=document.createElement('button');refresh.type='button';refresh.textContent='Apply changes & refresh';refresh.addEventListener('click',()=>document.getElementById('submit-button').click());refreshRow.append(refresh);parameters.append(refreshRow);
  for(const detail of config.querySelectorAll('details'))detail.open=false;
  config.open=true;

  const placeholder=document.createElement('div');placeholder.className='retrieval-tab-empty';placeholder.hidden=true;
  const placeholderTitle=document.createElement('h3'),placeholderText=document.createElement('p');placeholder.append(placeholderTitle,placeholderText);resultList.before(placeholder);
  function dirty(keys,message){
    for(const key of keys){state[key].status=state[key].data?'stale':'empty';state[key].message=message;}
    updateBadges();renderEmpty();
  }
  function scopeFor(target){
    const branch=target.closest('[data-parameter-branch]')?.dataset.parameterBranch;
    if(target.id.startsWith('weight-')||['rating-boost','preference-lambda','apply-preference-rerank'].includes(target.id))return ['hybrid'];
    return branch==='bm25'?['bm25','hybrid']:branch==='vector'?['vector','hybrid']:branch==='hybrid'?['hybrid']:modes;
  }
  for(const name of ['input','change'])form.addEventListener(name,event=>{
    if(event.target===modeInput)return;
    if(event.target.closest('.query-inspector'))return;
    if(busy){busy=false;for(const key of modes)if(state[key].status==='running')state[key].status=state[key].data?'stale':'empty';globalThis.RecipeRetrievalView?.action();}
    dirty(scopeFor(event.target),'Parameters changed · refresh to apply');
  });
  function updateBadges(){
    for(const key of modes){
      const record=state[key],count=record.data?.candidate_counts?.[key]??record.data?.result_count??0;
      buttons[key].querySelector('span').textContent=record.status==='ready'?(key==='hybrid'?`${record.data.result_count} shown`:`${count} candidates`):record.status==='running'?'Running…':record.status==='stale'?'Needs refresh':record.status==='failed'?'Failed · retry':'Not run';
      buttons[key].dataset.state=record.status;
    }
  }
  function renderEmpty(){
    const record=state[active];
    document.dispatchEvent(new CustomEvent('retrieval-view-updated',{detail:record}));
    placeholder.hidden=record.status==='ready'||record.status==='running';
    flowDisclosure.hidden=record.status!=='ready'&&record.status!=='running';
    if(!placeholder.hidden){
      placeholderTitle.textContent=record.status==='stale'?'Refresh to apply your changes':record.status==='failed'?'This retrieval did not complete':'Inspect this branch';
      placeholderText.textContent=record.message||(active==='hybrid'?'Refresh Hybrid to retrieve both branches and fuse their newest results.':`Run ${active==='bm25'?'BM25':'Vector'} independently, or refresh Hybrid to populate both branch lists.`);
    }
    if(record.status!=='ready'){
      resultList.classList.add('hidden');
      if(!busy)globalThis.RecipeRetrievalView?.clear();
    }
    status.textContent=record.status==='ready'?(active==='hybrid'?`Hybrid snapshot · ${record.data.result_count} shown · Refresh always reruns both branches.`:`${record.data.candidate_counts?.[active]??record.data.result_count} candidates · ${record.data.result_count} shown · ${record.data.from_hybrid_run?'From latest Hybrid run':'Independent branch run'} · Raw recall order`):record.status==='running'?'Retrieving with the current parameter snapshot…':record.message||'No current result snapshot.';
  }
  function select(key){
    if(!modes.includes(key))return;
    if(busy){
      const running=modes.find(k=>state[k].status==='running');
      if(running){state[running].status=state[running].data?'stale':'empty';state[running].message='Run interrupted when switching tabs. Refresh to retry.';}
      busy=false;globalThis.RecipeRetrievalView?.cancel();
    }
    active=key;modeInput.value=key;
    flowSummary.hidden=false;
    resultList.setAttribute('aria-labelledby',buttons[key].id);
    for(const k of modes){buttons[k].setAttribute('aria-selected',String(k===key));buttons[k].tabIndex=k===key?0:-1;}
    workspace.setAttribute('aria-labelledby',buttons[key].id);
    title.textContent=key==='hybrid'?'Compare, fuse, then recommend':key==='bm25'?'Inspect lexical recall':'Inspect semantic recall';
    description.textContent=key==='hybrid'?'BM25 on the left, Vector on the right. These are the same editable parameters used by the branch tabs.':`Edit ${key==='bm25'?'BM25':'Vector'} below and run it independently. Shared constraints apply to both branches.`;
    globalThis.RecipeRetrievalView?.updateSettings();
    document.querySelectorAll('#preference-settings input').forEach(field=>field.disabled=key!=='hybrid');
    document.getElementById('apply-preference-rerank').disabled=key!=='hybrid';
    for(const k of modes){
      cards[k].hidden=key!=='hybrid'&&k!==key;
      cards[k].querySelectorAll('input,select').forEach(field=>{field.disabled=cards[k].hidden;});
    }
    const record=state[key];
    globalThis.RecipeRetrievalView?.clear();
    if(record.status==='ready')globalThis.RecipeRetrievalView?.render(record.data,record.body);
    globalThis.RecipeFlow?.showRetrievalMode(key,record.status==='ready'?record.body:null,record.status==='ready'?record.data:null);
    empty.classList.add('hidden');updateBadges();renderEmpty();globalThis.RecipeRetrievalView?.action();
  }
  function projectBranch(data,body,branch){
    const raw=data.branch_results?.[branch];if(!raw || raw.status!=='complete')return null;
    const branchTimings={search_total_ms:null,rrf_ms:null,bm25_recall_ms:null,vector_recall_ms:null};
    branchTimings[branch+'_recall_ms']=data.timings?.[branch+'_recall_ms'];
    if(branch==='vector'){branchTimings.query_embedding_ms=data.timings?.query_embedding_ms;branchTimings.vector_query_ms=data.timings?.vector_query_ms;}
    else branchTimings.bm25_query_ms=data.timings?.bm25_query_ms;
    return {body:{...body,mode:branch,apply_preference_rerank:false},data:{...data,mode:branch,effective_mode:branch,from_hybrid_run:true,relaxation_baseline:raw.strict_baseline,results:raw.results,result_count:raw.results.length,
      timings:branchTimings,preferences:null,rrf:null,branches:{[branch]:data.branches[branch]},candidate_counts:{bm25:0,vector:0,[branch]:raw.candidate_count,union:raw.candidate_count,rrf:null},
      generation_candidate_ids:raw.generation_candidate_ids,generation_candidate_levels:raw.generation_candidate_levels||data.generation_candidate_levels,match_result_size:{value:raw.candidate_count,relation:'eq',scope:'branch_candidates'},warnings:branch==='bm25'?(data.warnings||[]).filter(w=>w.startsWith('BM25')||w.startsWith('Excluded ingredient')):[],
      executed_queries:{[branch]:data.executed_queries?.[branch]||[]},bm25_fallback:branch==='bm25'?data.bm25_fallback:null}};
  }
  globalThis.RecipeRetrievalTabs={
    get active(){return active;},select,
    prepare(body){
      if(body.mode==='hybrid')return;
      body.apply_preference_rerank=false;delete body.rrf_k;
      for(const key of Object.keys(body))if(key.startsWith('preference_weight_')||key==='preference_lambda'||key==='rating_boost')delete body[key];
      if(body.mode==='bm25'){delete body.vector_candidates;delete body.vector_scope_weight;delete body.vector_scope_query;delete body.vector_query;}
      else{delete body.bm25_candidates;delete body.bm25_available_boost;delete body.bm25_cuisine_boost;delete body.bm25_query;}
    },
    begin(body){
      dirty(body.mode==='hybrid'?modes:[body.mode,'hybrid'],'Retrieval changed · refresh Hybrid before generation');
      parameters.open=false;config.open=false;flowDisclosure.open=true;research.open=false;
      busy=true;state[body.mode].status='running';state[body.mode].message='';placeholder.hidden=true;updateBadges();renderEmpty();
    },
    complete(data,body){
      busy=false;if(body.mode!=='hybrid'&&data.branch_results?.[body.mode]?.strict_baseline)data={...data,relaxation_baseline:data.branch_results[body.mode].strict_baseline};state[body.mode]={data,body,status:'ready',message:''};
      if(body.mode==='hybrid')for(const branch of ['bm25','vector']){
        const projected=projectBranch(data,body,branch);
        if(projected)state[branch]={...projected,status:'ready',message:''};
        else if(data.branch_results?.[branch])state[branch]={data:null,body:null,status:'failed',message:'This branch failed in the Hybrid run. Run it independently to retry.'};
      }
      updateBadges();renderEmpty();
    },
    fail(body,message){busy=false;state[body.mode].status='failed';state[body.mode].message=message;updateBadges();renderEmpty();},
    reset(){
      busy=false;for(const key of modes)state[key]={data:null,body:null,status:'empty',message:''};
      parameters.open=false;config.open=true;globalThis.RecipeRetrievalView?.clear();updateBadges();renderEmpty();
    }
  };
  modeInput.addEventListener('change',()=>select(modeInput.value));
  document.addEventListener('workflow-intent-invalidated',()=>RecipeRetrievalTabs.reset());
  document.addEventListener('retrieval-fields-filled',()=>{RecipeRetrievalTabs.reset();select('hybrid');});
  select('hybrid');
})();
