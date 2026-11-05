(() => {
  const panel = document.querySelector('.search-panel');
  const requestSection = panel.querySelector('section');
  const form = document.getElementById('search-form');
  const input = document.getElementById('user-query');
  const stages = {};
  const buttons = {};
  const nav = document.createElement('nav');
  nav.className = 'workflow-nodes'; nav.setAttribute('aria-label', 'Recipe RAG workflow'); nav.hidden = true;
  const submit = document.createElement('button');
  submit.id = 'submit-request'; submit.type = 'button'; submit.textContent = 'Submit request →';
  globalThis.RecipeActionIcon?.(submit,'next','Start analysis');
  const composer = document.createElement('div'); composer.className = 'request-composer';
  input.before(composer); composer.append(input);
  const composerFooter = document.createElement('div'); composerFooter.className = 'composer-footer';
  composerFooter.append(document.getElementById('user-query-help'), submit); composer.append(composerFooter); panel.append(nav);
  let stepNumber = 0;
  for (const [name, label] of [['intent','Understand request'], ['retrieval','Retrieve recipes'], ['check','Check recipes'], ['generation','Generate recommendations']]) {
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.stage = name;
    button.innerHTML = `<span class="step-number">${String(++stepNumber).padStart(2, '0')}</span><span class="step-copy"><strong>${label}</strong><small>Not run</small></span>`;
    button.addEventListener('click', () => activate(name));
    buttons[name] = button; nav.append(button);
    const card = document.createElement('section');
    card.id = `stage-${name}`; card.className = 'workflow-card'; card.hidden = true;
    card.setAttribute('aria-label',label); stages[name] = card; panel.append(card);
  }
  const intentActions = requestSection.querySelector('.intent-actions');
  stages.intent.append(intentActions, document.getElementById('intent-panel'));
  stages.retrieval.append(form, document.getElementById('progress'), document.getElementById('empty'), document.getElementById('results'));
  const retrievalHeading = document.createElement('div');
  retrievalHeading.className = 'stage-heading';
  document.getElementById('retrieval-heading').textContent = 'Retrieve recipes';
  retrievalHeading.append(document.getElementById('retrieval-heading'), document.getElementById('submit-button'));
  form.prepend(retrievalHeading);
  const retrievalConfig = document.createElement('details');
  retrievalConfig.id = 'retrieval-configuration'; retrievalConfig.open = true;
  const configSummary = document.createElement('summary');
  configSummary.textContent = 'Retrieval configuration · expand to review or edit';
  retrievalConfig.append(configSummary);
  for (const child of [...form.children]) if (child !== retrievalHeading) retrievalConfig.append(child);
  form.append(retrievalConfig);
  stages.check.innerHTML=`<div class="stage-heading"><h2>Recipe Check</h2><div class="stage-heading-actions"><label>Check model <select id="check-model"><option value="deepseek-flash">DeepSeek Flash · direct</option><option value="gpt41-mini">GPT-4.1 mini · direct</option><option value="gpt41-nano">GPT-4.1 nano · direct</option><option value="gpt6">GPT-6 Astra · direct</option></select></label><button id="check-candidates" type="button">Check candidates</button></div></div><p class="field-help">Check which recipes meet your requirements before generating recommendations.</p><p id="check-status" role="status" aria-live="polite">Retrieve recipes first.</p><div id="check-output"></div>`;
  const localSummary=document.createElement('p');localSummary.id='local-check-summary';localSummary.className='local-check-summary field-help';localSummary.hidden=true;form.after(localSummary);
  stages.generation.innerHTML = `<h2>Your recipe recommendations</h2><p class="field-help">Recommendations use the retrieved candidate pool, up to 100 recipes. Original hard conditions are checked before confirmed recipes are recommended.</p>
    <div class="intent-actions"><label>Generation model <select id="generation-model"><option value="deepseek-flash">DeepSeek Flash · direct</option><option value="gpt41-mini">GPT-4.1 mini · direct</option><option value="gpt41-nano">GPT-4.1 nano · direct</option><option value="gpt6">GPT-6 Astra · direct</option></select></label><button id="generate-content" type="button">Generate</button></div>
    <details class="generation-advanced"><summary>Research settings</summary><label><input id="generation-recheck" type="checkbox" /> Recheck semantic decisions (experimental)</label><p class="field-help">Off by default. Recipe Check decides eligibility; Generation selects and explains those results. Enable only to study semantic disagreements. Structural, source and eligibility validation always remain active.</p></details><p id="generation-status" role="status" aria-live="polite">Retrieve recipes first.</p><div id="generation-output"></div>`;
function addHeading(stage, title, action) {
    const header = document.createElement('div'); header.className = 'stage-heading';
    const heading = document.createElement('h2'); heading.textContent = title;
    header.append(heading, action); stages[stage].prepend(header);
  }
  addHeading('intent', 'Understand your request', document.getElementById('analyze-intent'));
  const intentHeader = stages.intent.querySelector('.stage-heading');
  const intentHeaderActions = document.createElement('div'); intentHeaderActions.className = 'stage-heading-actions';
  intentHeaderActions.append(document.getElementById('intent-model').closest('label'), document.getElementById('analyze-intent'));
  intentHeader.append(intentHeaderActions); intentActions.remove();
  const generationTitle = stages.generation.querySelector('h2'); generationTitle.remove();
  addHeading('generation', 'Your recipe recommendations', document.getElementById('generate-content'));
  globalThis.RecipeActionIcon?.(document.getElementById('generate-content'),'generate','Generate recommendations');
  const generationActions = stages.generation.querySelector('.intent-actions');
  const generationHeaderActions = document.createElement('div'); generationHeaderActions.className = 'stage-heading-actions';
  generationHeaderActions.append(document.getElementById('generation-model').closest('label'), document.getElementById('generate-content'));
  stages.generation.querySelector('.stage-heading').append(generationHeaderActions); generationActions.remove();
  const intentOverview = document.createElement('section'); intentOverview.id = 'intent-overview'; intentOverview.hidden = true;
  stages.intent.insertBefore(intentOverview, document.getElementById('intent-panel'));
  const retrievalOverview = document.createElement('div'); retrievalOverview.id = 'retrieval-overview'; retrievalOverview.hidden = true;
  const retrievalOverviewDisclosure=document.createElement('details');retrievalOverviewDisclosure.id='retrieval-overview-disclosure';retrievalOverviewDisclosure.hidden=true;
  const overviewSummary=document.createElement('summary');overviewSummary.textContent='Executed queries & conditions';retrievalOverviewDisclosure.append(overviewSummary,retrievalOverview);form.after(retrievalOverviewDisclosure);
  const handoffs = {};
  for (const [stage, next, label] of [['intent','retrieval','Review retrieval fields'], ['retrieval','check','Review & check candidates'], ['check','generation','Continue to generation']]) {
    const handoff = document.createElement('div'); handoff.className = 'stage-handoff'; handoff.hidden = true;
    const message = document.createElement('span');
    const nextButton = document.createElement('button'); nextButton.type = 'button'; nextButton.textContent = label + ' →';
    globalThis.RecipeActionIcon?.(nextButton,'next',label);
    nextButton.addEventListener('click', () => { const destination=stage==='retrieval'&&checkedPool?.eligibility_id?'generation':next; activate(destination); const heading=stages[destination].querySelector('h2');heading.focus({preventScroll:true});heading.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'}); });
    handoff.append(message, nextButton); stages[stage].append(handoff); handoffs[stage] = handoff;
    if (stage === 'retrieval') retrievalHeading.after(handoff);  
    if (stage === 'intent') intentHeader.after(handoff);
    if (stage === 'check') stages.check.querySelector('.stage-heading').after(handoff);
  }
  for (const stage of Object.values(stages)) stage.querySelector('h2').tabIndex = -1;
  let revision = 0, submitted = '', interpretation = null, retrieval = null, generating = false;
  let retrievalController = null, generationController = null;
  let checkedPool=null,checkController=null,checking=false,checkTicket=0;
  function status(stage, text, backendMs) {
    const state = text === 'Processing' ? 'processing' : text === 'Complete' ? 'complete' : text === 'Failed' ? 'failed' : text === 'Not run' ? 'ready' : 'review';
    if(stage==='intent')submit.disabled=state==='processing';
    const elapsed = typeof backendMs === 'number' && Number.isFinite(backendMs) && backendMs >= 0 ? backendMs : null;
    const label = buttons[stage].querySelector('small');
    label.textContent = text + (elapsed === null ? '' : ` · Backend ${elapsed < 1000 ? elapsed.toFixed(0) + ' ms' : (elapsed / 1000).toFixed(2) + ' s'}`);
    const ranges = {intent:'Backend intent parsing: preparation, model call and validation.', retrieval:'Backend retrieval: preparation, recall, fusion and reranking.', check:'Backend recipe checks: source fetch, local and semantic validation.', generation:'Backend generation: recipe fetching, model call and output validation.'};
    label.title = elapsed === null ? text : `${ranges[stage]} ${backendMs} ms. Excludes browser and network round-trip time.`;
    if (elapsed === null) delete buttons[stage].dataset.backendMs;
    else buttons[stage].dataset.backendMs = String(backendMs);
    buttons[stage].dataset.state = state; stages[stage].dataset.state = state;
    stages[stage].setAttribute('aria-busy', String(state === 'processing'));
    if(stage==='check'){const action=document.getElementById('check-candidates');globalThis.RecipeActionIcon?.(action,'analyze',state==='processing'?'Checking candidates':state==='complete'?'Check again':'Check candidates',state==='processing');}
    if (stage === 'generation') {
      const action=document.getElementById('generate-content');
      const label=state === 'processing' ? 'Generating recommendations' : state === 'complete' ? 'Generate again' : 'Generate recommendations';
      if (globalThis.RecipeActionIcon) RecipeActionIcon(action,'generate',label,state === 'processing');
      else action.textContent=label;
    }
  }
  function activate(name) {
    if (buttons[name].hidden || buttons[name].disabled) return;
    for (const key of Object.keys(stages)) {
      stages[key].hidden = key !== name;
      stages[key].classList.toggle('stage-arriving',key===name);
      buttons[key].setAttribute('aria-current',key === name ? 'step' : 'false');
    }
  }
  function clearGenerated(message='Needs rerun') {
    generationController?.abort(); generationController = null; generating = false;
    document.getElementById('generation-output').replaceChildren();
    document.getElementById('generation-status').textContent = message;
    document.getElementById('generate-content').disabled = !(checkedPool?.qualified_recipe_ids?.length || checkedPool?.near_miss_recipe_ids?.length);
    status('generation',message);
  }
  function clearChecked(message='Needs rerun') {
    checkTicket++;checkController?.abort();checkController=null;checking=false;checkedPool=null;
    const forward=handoffs.retrieval.querySelector('button');if(globalThis.RecipeActionIcon)RecipeActionIcon(forward,'next','Review & check candidates');else forward.textContent='Review & check candidates';
    document.getElementById('check-output').replaceChildren();document.getElementById('check-status').textContent=message;
    document.getElementById('check-candidates').disabled=!retrieval?.data.results.length;
    handoffs.check.hidden=true;buttons.generation.disabled=true;status('check',message);clearGenerated(message);
    localSummary.hidden=true;
  }
  function invalidateRetrieval(message='Needs rerun') {
    handoffs.intent.hidden = true; handoffs.retrieval.hidden = true; retrievalOverview.hidden = true; retrievalOverviewDisclosure.hidden=true;
    globalThis.RecipeRetrievalFlow?.clear();
    revision++; retrievalController?.abort(); retrievalController=null; retrieval=null;
    document.getElementById('submit-button').disabled=false;
    document.getElementById('results').classList.add('hidden');
    document.getElementById('results').replaceChildren();
    document.getElementById('progress').classList.add('hidden');
    status('retrieval',message); clearChecked(message); buttons.check.disabled=true; buttons.generation.disabled=true;
  }
  function invalidateIntent() {
    document.dispatchEvent(new Event('workflow-intent-invalidated'));
    intentOverview.hidden=true; intentOverview.replaceChildren(); retrievalOverview.hidden=true;retrievalOverviewDisclosure.hidden=true;
    interpretation=null; invalidateRetrieval(); status('intent','Needs rerun');
    buttons.retrieval.disabled = true; buttons.generation.disabled = true;
    buttons.retrieval.disabled=true;
    if (!nav.hidden) activate('intent');
  }
  input.addEventListener('input',invalidateIntent);
  document.getElementById('intent-model').addEventListener('change',invalidateIntent);
  for (const eventName of ['input','change']) form.addEventListener(eventName,event => {
    if(event.target.id==='mode')return;
    if(event.target.closest('.query-inspector'))return;
    if (interpretation) invalidateRetrieval();
  });
  submit.addEventListener('click',() => {
    if (!input.value.trim()) { input.focus(); input.reportValidity(); return; }
    invalidateIntent(); submitted=input.value; nav.hidden=false;
    buttons.intent.hidden=false; buttons.retrieval.hidden=false; buttons.check.hidden=false;buttons.check.disabled=true; buttons.generation.hidden=false; buttons.retrieval.disabled=true; buttons.generation.disabled=true;
    status('intent','Not run'); status('retrieval','Not run'); status('check','Not run');status('generation','Not run'); activate('intent');document.getElementById('analyze-intent').click();
  });

  const clone = value => JSON.parse(JSON.stringify(value));
  globalThis.RecipeFlow = {
    startIntent() {
      invalidateIntent();
      if (!submitted || submitted !== input.value) {
        document.getElementById('intent-message').textContent='Submit the current request first.';
        return false;
      }
      status('intent','Processing'); return true;
    },
    intentComplete(data) {
      if (data.raw_query !== submitted || submitted !== input.value) return;
      status('intent',data.parsed.status === 'ready' ? 'Complete' : 'Review required',data.intent_parse_ms);
      if (data.parsed.status !== 'ready' || data.parsed.intent !== 'recipe_search') {document.getElementById('intent-panel').open=true; return;}
      renderIntentOverview(data);
      document.getElementById('intent-panel').open = false;
      interpretation=clone(data); buttons.retrieval.hidden=false; buttons.retrieval.disabled=false;
      status('retrieval','Not run');
      retrievalConfig.open = true;
      handoffs.intent.querySelector('span').textContent = 'Intent ready. Your retrieval fields have been filled in and can be edited.';
      handoffs.intent.hidden = false;
    },
    intentFailed() { status('intent','Failed'); },
    cancelRetrieval(){invalidateRetrieval('Needs rerun');},
    showRetrievalMode(mode,body,data){
      handoffs.retrieval.hidden=true;
      if(!data || !body || !interpretation){retrieval=null;buttons.check.disabled=true;clearChecked('Not run');return;}
      if(!retrieval || JSON.stringify(retrieval.body)!==JSON.stringify(body) || JSON.stringify(retrieval.data)!==JSON.stringify(data)){
        this.retrievalComplete({revision,body:clone(body),intent:clone(interpretation),query:submitted},data);
      }
      handoffs.retrieval.hidden=!retrieval?.data.results.length;
    },
    startRetrieval(body) {
      if (!interpretation || submitted !== input.value) return null;
      invalidateRetrieval(); retrievalController=new AbortController();
      retrievalConfig.open = false;
      renderRetrievalOverview(body);
      configSummary.textContent = globalThis.RecipeRetrievalTabs ? 'Shared constraints & recommendation preferences' : `Search configuration · ${body.query} · ${body.mode === 'hybrid' ? 'Hybrid' : body.mode.toUpperCase()} · ${body.size} results`; 
      buttons.generation.hidden=false; buttons.generation.disabled=true; status('retrieval','Processing');
      return {revision, signal:retrievalController.signal, body:clone(body), intent:clone(interpretation), query:submitted};
    },
    current(token) { return Boolean(token && token.revision === revision); },
    retrievalComplete(token,data) {
      if (!this.current(token)) return;
      retrieval={...token,data:clone(data)}; status('retrieval','Complete',data.timings?.search_total_ms);
      document.getElementById('retrieval-heading').textContent = 'Retrieved recipes';
      buttons.check.disabled=!data.results.length;buttons.generation.disabled=true;
      clearChecked(data.results.length ? 'Not run' : 'No recipes available');
      handoffs.intent.hidden = false;
      handoffs.retrieval.querySelector('span').textContent = `${data.results.length} recipes retrieved · ${token.body.mode === "hybrid" ? "Hybrid fusion" : token.body.mode.toUpperCase()+" recall"}. Review the results or check candidate eligibility.`;
      if(data.relaxation?.selected_plan){const r=data.relaxation;handoffs.retrieval.querySelector('span').textContent += ` Strict candidates: ${r.strict_candidate_count} · Relaxed: ${r.selected_plan.actions.map(a=>a.type==='drop_ingredient'?'remove '+a.value:a.field+' range').join('; ')} · Additional unique candidates: ${new Set(Object.entries(data.generation_candidate_levels||{}).filter(([,m])=>m.source_level==='relaxed').map(([id])=>id)).size}.`;}
      if(data.results.length)runChecks(true);
      handoffs.retrieval.hidden = !data.results.length;
    },
    retrievalFailed(token) { if (this.current(token)) {retrievalConfig.open=true; status('retrieval','Failed'); clearGenerated('Retrieve successfully before generating.');} },
  };
  buttons.intent.hidden=false; buttons.retrieval.hidden=false; buttons.check.hidden=false;buttons.check.disabled=true; buttons.generation.hidden=false; buttons.retrieval.disabled=true; buttons.generation.disabled=true;
  document.getElementById('generate-content').disabled=true;document.getElementById('check-candidates').disabled=true;
  document.getElementById('generation-model').addEventListener('change',()=>clearGenerated('Needs rerun'));
  document.getElementById('generation-recheck').addEventListener('change',()=>clearGenerated('Needs rerun'));
  document.getElementById('check-model').addEventListener('change',()=>{clearChecked();if(retrieval?.data.results.length)runChecks(true);});
  const textElement = (tag,text,className='') => {const node=document.createElement(tag);node.textContent=text;node.className=className;return node;};
  function overviewGroup(title, values, className='') {
    const group=document.createElement('section'); group.className='overview-group '+className;
    group.append(textElement('h3',title));
    const chips=document.createElement('div'); chips.className='overview-chips';
    for (const value of values.length ? values : ['None specified']) chips.append(textElement('span',value,'overview-chip'));
    group.append(chips); return group;
  }
  function renderIntentOverview(data) {
    const parsed=data.parsed, extraction=parsed.extraction;
    intentOverview.replaceChildren(); intentOverview.hidden=false;
    const target=document.createElement('div'); target.className='overview-target';
    target.append(textElement('h3','Search target'),textElement('p',parsed.retrieval_content || parsed.search_text || data.raw_query));
    intentOverview.append(target);
    const tokens=data.token_usage || {}, cost=data.cost_estimate || {};
    const value=x=>Number.isInteger(x)?x.toLocaleString('en-US'):'Unavailable';
    const costText=cost.status==='estimated'?(cost.min_usd===cost.max_usd?'$'+cost.estimated_usd.toFixed(8):'$'+cost.min_usd.toFixed(8)+' – $'+cost.max_usd.toFixed(8)):'Unavailable';
    const usageLine=textElement('p',`Tokens · Input ${value(tokens.input_tokens)} · Output ${value(tokens.output_tokens)} · Total ${value(tokens.total_tokens)} · Estimated cost (USD) ${costText}`,'field-help intent-usage-overview');
    usageLine.title=cost.note || 'Usage or verified pricing unavailable; not an indication of zero cost.'; intentOverview.append(usageLine);
    const ingredients=extraction?.ingredients || [];
    const names=role=>extraction ? ingredients.filter(item=>item.entity_type==='specific' && item.role===role).map(item=>item.name)
      : (data.constraint_rows || []).filter(row=>['ingredient_'+role,'ingredients_'+role].includes(row.field)).flatMap(row=>Array.isArray(row.value) ? row.value : [row.value]).filter(Boolean);
    const groups=document.createElement('div'); groups.className='overview-grid';
    groups.append(overviewGroup('Must include · retrieval filter',names('required').map(name=>name+' · Core: '+(ingredients.some(i=>i.name===name&&i.core)?'yes':'no')),'include-group'),overviewGroup('Must exclude · retrieval filter',names('excluded'),'exclude-group'));
    const dish=parsed.dish_name||extraction?.dish_name,type=parsed.dish_type||extraction?.dish_type;
    if(dish){const target=overviewGroup('Dish identity',[dish,...(type?[`Dish type: ${type}`]:[])]);target.append(textElement('p','Dish-name words belong to the dish identity. Only separately requested ingredients become Must include.','field-help'));groups.append(target);}
    const finalCuisine=(parsed.cuisine||extraction?.cuisine) && (parsed.cuisine_role||extraction?.cuisine_role)==='required' && !(parsed.dish_name||extraction?.dish_name) && !(parsed.dish_type||extraction?.dish_type);
    if(finalCuisine)groups.append(overviewGroup('Final requirement · Generate must confirm',[parsed.cuisine||extraction.cuisine],'include-group'));
    const preferences=[...names('available').map(x=>'Available: '+x), ...names('prefer'),...names('avoid').map(x=>'Avoid: '+x),...(finalCuisine?['meal_type','dish_type']:['cuisine','meal_type','dish_type']).map(key=>parsed[key] || extraction?.[key]).filter(Boolean),...(extraction?.soft_preferences || [])];
    groups.append(overviewGroup('Ranking preferences', [...new Set(preferences)]));
    if(extraction?.required_expression)groups.append(overviewGroup('Required ingredient logic',[RecipeRequired.format(extraction.required_expression)],'required-logic-group'));
    if(extraction?.generation_notes?.length)groups.append(overviewGroup('Explanation requests · no recipe changes',extraction.generation_notes));
    const bounds=extraction?.bounds || [];
    if(bounds.length) groups.append(overviewGroup('Numeric conditions · review in retrieval',bounds.map(item=>`${item.field.replaceAll('_',' ')} ${{lt:'<',lte:'≤',gt:'>',gte:'≥',eq:'='}[item.operator]} ${item.value} ${item.unit}${item.basis==='not_applicable'?'':' · '+item.basis.replaceAll('_',' ')}`)));
    const categories=ingredients.filter(item=>item.entity_type==='category').map(item=>item.name+' · '+item.role);
    if(categories.length) {const group=overviewGroup('Category conditions · not hard filters',categories,'category-group'); group.append(textElement('p','Positive categories may boost keyword matches. Semantic category checks occur in Recipe Check.','field-help'));groups.append(group);}
    intentOverview.append(groups);
    if(!extraction) intentOverview.append(textElement('p','Jev does not provide equivalent ingredient category, AND/OR grouping or semantic conflict extraction. Review its full interpretation.','field-help'));
    intentOverview.append(textElement('p','These fields are prepared for retrieval. Review and edit the actual filters in the next step.','field-help'));
  }
  function renderRetrievalOverview(body) {
    retrievalOverview.replaceChildren(); retrievalOverview.hidden=false;retrievalOverviewDisclosure.hidden=false;retrievalOverviewDisclosure.open=false;
    retrievalOverview.append(overviewGroup('BM25 query', [body.bm25_query ?? body.query]),overviewGroup('Vector semantic query',[body.vector_query ?? body.query]),overviewGroup('Must include',body.include_ingredients || [],'include-group'),overviewGroup('Must exclude',body.exclude_ingredients || [],'exclude-group'));
    if(body.required_expression)retrievalOverview.append(overviewGroup('Required ingredient logic',[RecipeRequired.format(body.required_expression)],'required-logic-group'));
    if(body.category_required?.length)retrievalOverview.append(overviewGroup('Required categories',body.category_required));
    if(body.category_excluded?.length)retrievalOverview.append(overviewGroup('Excluded categories',body.category_excluded));
    const preferences=Object.entries(body).filter(([key,value])=>key.startsWith('preference_') && Array.isArray(value)).flatMap(([key,value])=>value.map(x=>key.replace('preference_','').replaceAll('_',' ')+': '+x));
    if(preferences.length) retrievalOverview.append(overviewGroup('Prefer / rank',preferences));
    retrievalOverview.append(overviewGroup('Vector scope · ranking only',[body.vector_scope_query || 'Off',`β ${body.vector_scope_weight ?? 0}`]),overviewGroup('Final cuisine requirement',body.cuisine_target && body.cuisine_role==='required' && !body.dish_name_target && !body.dish_type_target ? [body.cuisine_target] : ['None · cuisine affects ranking only']),overviewGroup('Meal · explanation only',body.meal_type_target ? [body.meal_type_target] : []));
    const other=[...(body.labels || []).map(x=>'Label: '+x),...(body.numeric_filters || []).map(x=>`${x.field} ${x.operator} ${x.value}`)];
    if(body.cook_time) other.push('Time range: '+body.cook_time);
    if(body.max_total_time_minutes!=null) other.push('Total time ≤ '+body.max_total_time_minutes+' min');
    if(body.max_calories!=null) other.push('Calories ≤ '+body.max_calories+' / serving');
    if(other.length) retrievalOverview.append(overviewGroup('Other filters',other));
  }
  function jsonViewer(value, label) {
    const wrapper=document.createElement('div'); wrapper.className='json-copy-viewer';
    const serialized=typeof value==='string'?value:JSON.stringify(value,null,2);
    const button=textElement('button','Copy '+label,'secondary'); button.type='button';
    button.setAttribute('aria-label','Copy '+label); button.setAttribute('aria-live','polite');
    button.addEventListener('click',async()=>{
      try { await navigator.clipboard.writeText(serialized); button.textContent='Copied'; }
      catch(error) { button.textContent='Copy failed — select text below'; }
      setTimeout(()=>{button.textContent='Copy '+label;},2500);
    });
    wrapper.append(button,textElement('pre',serialized)); return wrapper;
  }
  function generationUsage(data, label='This generation') {
    const section=document.createElement('section'); section.className='generation-usage';
    const tokens=data.token_usage || {}, cost=data.cost_estimate || {};
    const n=value=>Number.isInteger(value)?value.toLocaleString('en-US'):'Unavailable';
    const usd=value=>'$'+Number(value).toFixed(8);
    const price=cost.status==='estimated'?(cost.min_usd===cost.max_usd?usd(cost.max_usd):usd(cost.min_usd)+' – '+usd(cost.max_usd)):cost.status==='partial'?usd(cost.known_min_usd)+' – '+usd(cost.known_max_usd)+' known subtotal · incomplete':'Unavailable';
    section.append(textElement('p',`${label} · Input ${n(tokens.input_tokens)} · Output ${n(tokens.output_tokens)} · Total ${n(tokens.total_tokens)} · Cached input ${n(tokens.cached_input_tokens)}`,'field-help'),textElement('p',`Estimated cost · USD ${price}`,'field-help'));
    section.title=cost.note || 'Provider usage or verified pricing unavailable; not an indication of zero cost.';
    return section;
  }
  function appendModelInput(value, target=document.getElementById('generation-output')) {
    if (!value) return;
    const details = document.createElement('details'); details.className = 'model-input-viewer';
    details.append(textElement('summary', 'View model input · this generation'), textElement('p', 'Prepared provider request body, including instructions, recipe records and settings. A failed attempt may have stopped before dispatch; check diagnostics and recorded calls. Authentication headers are not included.', 'field-help'), jsonViewer(value, 'input JSON'));
    target.append(details);
  }
  function ingredientEvidenceText(check){
    const sources=check.evidence_sources||[];
    return sources.length?sources.map(item=>`${item.value} (${item.field==='extract_ingredients'?`mentioned in instructions · ${item.usage_confirmed_by_model==='preparation'?'Used in preparation · model check':item.usage==='preparation'?'Used in preparation':item.usage==='serving_optional'?'Serving suggestion':'Use not confirmed'}`:'ingredient list'})`).join('; '):(check.evidence||[]).join(', ');
  }
  const targetReached = data => data.eligibility_stats?.stop_reason==='enough_qualified_candidates' && data.eligibility_stats?.prefix_complete===true;
  const uncheckedLabel = data => targetReached(data)?'not needed (target reached)':'not checked';
  const exclusionMet = c => c.role==='excluded' && c.decision==='fail' && (['ingredient','category'].includes(c.kind)||!c.kind);
  const conditionLabel = c => exclusionMet(c)?`Contains ${c.name||c.category}`:`${c.role||'condition'} · ${c.category||c.name||c.kind||'Requirement'}`;
  function renderGenerated(data, snapshot) {
    const root=document.getElementById('generation-output'); root.replaceChildren();
    const usageDisclosure=document.createElement('details');usageDisclosure.className='generation-usage-disclosure';usageDisclosure.append(textElement('summary','Token usage & estimated cost'),generationUsage(data));
    for(const [phase,usage] of Object.entries(data.phase_usage || {})) if(usage.token_usage.call_count) usageDisclosure.append(generationUsage(usage,phase==='category_check'?'Eligibility checks':'Recommendation summary'));
    const output=document.createElement('article'); output.className='generated-answer'; output.setAttribute('aria-label','Recipe recommendations'); root.append(output);
    const research=document.createElement('details'); research.className='generation-research'; research.append(textElement('summary','Research details · checks, model input & diagnostics'));
    for (const warning of data.warnings) research.append(textElement('p',warning,'search-warning'));
    const introRow=document.createElement('div');introRow.className='generation-intro-row';
    const lead=document.createElement('div');lead.className='generation-lead';lead.append(textElement('p',data.summary,'generated-summary'));
    const runNote=document.createElement('aside');runNote.className='generation-status-note';runNote.hidden=!(data.constraint_counts||data.eligibility_stats);runNote.setAttribute('aria-label','Qualification and generation overview');runNote.append(textElement('h3','Run overview'));introRow.append(lead,runNote);output.append(introRow);
    if (data.recommendation_limit) research.append(textElement('p', `Showing ${data.recommendations.length} recommendations · requested target ${data.requested_recipe_count||5}${data.requested_recipe_count ? ' by you' : ' by default'} · current recommendation limit ${data.recommendation_limit}. Fewer may be available after constraint checks. Unconfirmed candidates are not counted as recommendations.`, 'field-help'));
    if(data.constraint_counts) runNote.append(textElement('p',`${data.constraint_counts.pass} qualified · ${data.constraint_counts.near_miss?data.constraint_counts.near_miss+' close alternatives · ':''} ${data.constraint_counts.fail} not eligible · ${data.constraint_counts.unknown} unconfirmed · ${data.constraint_counts.not_checked||0} ${uncheckedLabel(data)}`,'field-help'));
    if(data.eligibility_stats){
      const stats=data.eligibility_stats,stops={enough_qualified_candidates:'Qualified target reached',candidate_pool_exhausted:'Candidate pool exhausted',batch_failures:'Some batches need retry',near_miss_target_reached:'Close alternative target reached'};
      runNote.append(textElement('p',`Qualification target ${stats.target} · Recommendation target ${data.requested_recipe_count||5} · Model calls ${(data.model_calls||[]).length} · Stop: ${stops[stats.stop_reason]||stats.stop_reason}`,'generation-run-summary field-help'));
    }
    const recommendationList = document.createElement('div'); recommendationList.className = 'generated-list'; output.append(recommendationList);
    const recipes=new Map(data.recipes.map(recipe=>[recipe.recipe_id,recipe]));
    const assessments=new Map(data.assessments.map(item=>[item.recipe_id,item]));

    for (const recommendation of [...data.recommendations,...(data.close_alternatives||[])]) {
      const alternative=(data.close_alternatives||[]).includes(recommendation);
      const recipe=recipes.get(recommendation.recipe_id), assessment=assessments.get(recommendation.recipe_id);
      const row=document.createElement('div');row.className='generation-recipe-row';
      const card=document.createElement('article');card.className='generated-recipe';card.dataset.recipeId=recipe.recipe_id;
      if(alternative)card.classList.add('close-alternative');
      const notes=document.createElement('aside');notes.className='generation-recipe-notes';
      for(const waiver of assessment.waived_conditions||[])notes.append(textElement('p',waiver.reason,'search-warning ingredient-waiver'));
      notes.setAttribute('aria-label',`Matching information for ${recipe.name}`);row.append(card,notes);
      const title=textElement('button',`${(alternative?data.close_alternatives:data.recommendations).indexOf(recommendation) + 1}. ${recipe.name}`,'recipe-title'); title.type='button';
      title.addEventListener('click',()=>loadRecipeDetail(recipe.recipe_id,title,recipe));
      const retrieved = snapshot.data.results.find(item => String(item.document_id || item.recipe_id) === String(recipe.recipe_id));
      const photo = document.createElement('img'); photo.className = 'generated-photo';
      const fallback = retrieved?.fallback_image_url || recipe.fallback_image_url || '/assets/recipe-icons/default.svg';
      const safeImage = value => { if (typeof value !== 'string' || !value.trim()) return null; try { const url = new URL(value, location.origin); return ['http:','https:'].includes(url.protocol) ? url.href : null; } catch { return null; } };
      photo.src = safeImage(retrieved?.display_image_url || recipe.display_image_url) || safeImage(fallback) || '/assets/recipe-icons/default.svg';
      photo.addEventListener('load',()=>visual.classList.toggle('small-source-image',photo.naturalWidth < 400));
      photo.alt = recipe.name; photo.loading = 'lazy'; photo.width = 360; photo.height = 280;
      
      const visual = document.createElement('button'); visual.type = 'button'; visual.className = 'generated-visual'; visual.setAttribute('aria-label', `Preview ${recipe.name}`); visual.append(photo); visual.addEventListener('click', () => loadRecipeDetail(recipe.recipe_id, visual,{...recipe,display_image_url:photo.src}));
      RecipeImage.bind(photo,card,{...recipe,...retrieved},isFallback=>{row.classList.toggle('recipe-fallback-row',isFallback);visual.classList.toggle('category-icon',isFallback);});
      const body = document.createElement('div'); body.className = 'generated-body';
      const introduction=document.createElement('div');introduction.className='generated-introduction';
      const heading = document.createElement('h3'); heading.className = 'answer-recipe-title'; heading.append(title); card.append(heading); 
      const facts = document.createElement('div'); facts.className = 'generated-facts';
      const finite = value => typeof value === 'number' && Number.isFinite(value);
      if (finite(recipe.total_time_minutes)) facts.append(textElement('span', `${recipe.total_time_minutes} min total`));
      if (finite(recipe.aggregatedrating) && recipe.aggregatedrating > 0) facts.append(textElement('span', `Rating ${recipe.aggregatedrating} / 5`));
      if (finite(recipe.calories)) facts.append(textElement('span', `${recipe.calories} kcal / serving`));
      notes.append(facts);
      if(alternative)for(const deviation of recommendation.deviations||assessment.deviations||[])notes.append(textElement('p','Differs from your request: '+deviation.reason,'search-warning'));
      if(recipe.description && !/^Make and share this .* recipe from Food\.com\.?$/i.test(recipe.description.trim())) introduction.append(textElement('p',recipe.description,'generated-description'));
      const contextEvidence=document.createElement('div');contextEvidence.className='generated-context-evidence';
      if(recipe.context_matches?.length){
        const key=value=>String(value).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
        const matches=[...new Map(recipe.context_matches.map(m=>[m.field+':'+key(m.value),m])).values()];
        contextEvidence.append(textElement('p',matches.map(m=>`${m.field==='meal_type'?'Meal':'Cuisine'}: ${m.value}${key(m.evidence)===key(m.value)?'':' ('+m.evidence+')'}`).join(' · '),'generated-context-matches'));
      }
      const fromInstructions=[...new Set([...(assessment.checks||[]).filter(c=>c.status==='matched'),...(recipe.ingredient_preference_matches||[]),...(retrieved?.preference_evidence||[]).filter(e=>e.match_score>0).flatMap(e=>e.checks||[])].flatMap(c=>c.evidence_sources||[]).filter(s=>s.field==='extract_ingredients').map(s=>s.value))];
      const instructionEvidence=fromInstructions.length?textElement('p','Ingredient evidence from instructions: '+fromInstructions.join(', ')+'.','generated-instruction-matches'):null;
      const explanation=textElement('p',recommendation.reason,'generated-reason');
      const bubble=document.createElement('button'); bubble.type='button'; bubble.className='matching-bubble'; bubble.title='Why this recipe matches'; bubble.setAttribute('aria-label',`Show matching details for ${recipe.name}`); bubble.setAttribute('aria-expanded','false');
      const icon=document.createElementNS('http://www.w3.org/2000/svg','svg'); icon.setAttribute('viewBox','0 0 24 24'); icon.setAttribute('aria-hidden','true');
      const path=document.createElementNS(icon.namespaceURI,'path'); path.setAttribute('d','M9 5h12M9 12h12M9 19h12M2 5l1 1 3-3M2 12l1 1 3-3M2 19l1 1 3-3'); icon.append(path); bubble.append(icon,textElement('span','Why this recipe')); notes.prepend(bubble); body.append(introduction,explanation);
      const avoided=(retrieved?.preference_evidence || []).filter(item=>item.group==='avoid' && item.match_score>0).flatMap(item=>item.matched || []);
      if(avoided.length) notes.append(textElement('p','One thing to keep in mind: it also lists '+avoided.join(', ')+', which you prefer to avoid.','search-warning')); 
      const rankingDetails = document.createElement('div'); rankingDetails.className='ranking-explanation'; rankingDetails.id='matching-details-'+recipe.recipe_id; rankingDetails.hidden=true; bubble.setAttribute('aria-controls',rankingDetails.id);
      bubble.addEventListener('click',()=>{rankingDetails.hidden=!rankingDetails.hidden; bubble.setAttribute('aria-expanded',String(!rankingDetails.hidden)); bubble.title=rankingDetails.hidden?'Show matching details':'Hide matching details'; bubble.setAttribute('aria-label',`${bubble.title} for ${recipe.name}`);}); 
      const signals = document.createElement('ul'); signals.className = 'generated-signals';
      const labels = {available:'Available ingredients',prefer:'Preferred ingredients',avoid:'Avoided ingredients present',cuisine:'Cuisine match',meal_type:'Meal match',dish_type:'Dish match',quick:'Quick / fast',easy:'Easy',flavor:'Flavor match'};
      for (const evidence of retrieved?.preference_evidence || []) {
        if (!(evidence.match_score > 0)) continue;
        if (evidence.group === 'healthy') {
          const nutritionNames = {proteincontent:'Protein',sugarcontent:'Sugar',fatcontent:'Fat',cholesterolcontent:'Cholesterol',sodiumcontent:'Sodium'};
          for (const check of evidence.checks || []) if (check.status === 'met') signals.append(textElement('li', `${nutritionNames[check.field] || check.field}: ${check.value} ${check.unit} / serving · ${check.operator === 'gte' ? '≥' : '≤'} ${check.threshold} ${check.unit}`, 'nutrition-signal'));
        } else {
          const matches = (evidence.matched || []).join(', ');
          for(const check of evidence.checks||[])if(check.evidence_sources?.length)signals.append(textElement('li',`${check.target}: ${ingredientEvidenceText(check)}`,'ingredient-source-signal'));
          const quick = evidence.group === 'quick' ? (evidence.checks || []).find(c => c.value != null) : null;
          signals.append(textElement('li', `${labels[evidence.group] || evidence.group}${matches ? ': ' + matches : quick ? ': ' + quick.value + ' min total' : ': matched'}`, evidence.group === 'avoid' ? 'caution-signal' : ''));
        }
      }
      if (signals.childNodes.length) rankingDetails.append(signals);
      else rankingDetails.append(textElement('p','No additional preference matches recorded.'));
      if(contextEvidence.childNodes.length)rankingDetails.append(contextEvidence);
      if(instructionEvidence)rankingDetails.append(instructionEvidence);
      notes.insertBefore(rankingDetails,facts);
      const essentials = document.createElement('details'); essentials.className = 'recipe-essentials'; essentials.append(textElement('summary','Ingredients & instructions'));
      const ingredientSection = document.createElement('section'); ingredientSection.append(textElement('h4', 'Ingredients'));
      if(recipe.ingredients?.length) {const list=document.createElement('ul'); list.className='generated-ingredients'; list.classList.toggle('ingredients-two-columns',recipe.ingredients.length >= 6); for(const ingredient of recipe.ingredients) list.append(textElement('li',ingredient)); ingredientSection.append(list);}
      else ingredientSection.append(textElement('p','Not recorded.','generated-ingredients'));
      ingredientSection.className='generation-source-ingredients';essentials.append(ingredientSection);
      const instructionSection = document.createElement('section'); instructionSection.append(textElement('h4', 'Instructions'));
      if (recipe.instructions?.length) {
        const steps = document.createElement('ol');
        for (const step of recipe.instructions) steps.append(textElement('li', step));
        instructionSection.append(steps);
      } else instructionSection.append(textElement('p', 'Instructions not recorded.'));
      essentials.append(instructionSection); body.append(essentials);
      if (assessment.unresolved.length) notes.append(textElement('p', `Not confirmed: ${assessment.unresolved.join(', ')}. This recipe may not satisfy these hard constraints.`, 'search-warning'));
      if (assessment.checks.length) {
        const checks = document.createElement('details'); checks.className = 'generated-checks'; checks.append(textElement('summary', 'Hard condition checks'));
        if(assessment.required_expression)checks.append(textElement('p',`Required logic: ${RecipeRequired.format(assessment.required_expression)} · ${assessment.required_group_status}`));
        for (const check of assessment.checks) checks.append(textElement('p', `${conditionLabel(check)}${check.kind==='ingredient'||check.kind==='category'?' · Core: '+(check.core?'yes':'no'):''}: ${check.waived?'Waived for relaxed recall':check.status}${check.alternative_not_needed&&!check.waived?' (not decisive for this group)':''}. ${check.reason} ${check.evidence.length ? 'Evidence: ' + ingredientEvidenceText(check) : ''}`, 'field-help'));
        notes.append(checks);
      }
      card.append(visual, body);
      recommendationList.append(row);
    }
    const summaryItems=[...data.recommendations,...(data.close_alternatives||[])];
    if (summaryItems.length) {
      const comparison = document.createElement('section'); comparison.className = 'recipe-comparison';comparison.tabIndex=0;comparison.setAttribute('aria-label','Recipe summary and requirement differences; scroll horizontally if needed');
      const table = document.createElement('table'); table.append(textElement('caption', 'Recipe summary'));
      const head = document.createElement('thead'); const header = document.createElement('tr');
      for (const label of ['Recipe', 'Flavor / style', 'Best for', 'Requirement differences']) {const cell = textElement('th', label); cell.scope = 'col'; header.append(cell);}
      head.append(header); table.append(head); const rows = document.createElement('tbody');
      for (const item of summaryItems) {
        const row = document.createElement('tr'); const name = textElement('th', recipes.get(item.recipe_id).name); name.scope = 'row';
        row.append(name, textElement('td', item.flavor || 'Not specified'), textElement('td', item.best_for || item.reason),textElement('td',(data.close_alternatives||[]).includes(item)?(item.deviations||assessments.get(item.recipe_id)?.deviations||[]).map(d=>d.reason).join(' '):'Meets checked requirements')); rows.append(row);
      }
      table.append(rows); comparison.append(table); output.append(comparison);
    }
    const excludedCandidates=data.assessments.filter(item=>item.status==='fail');
    if(excludedCandidates.length){
      const excluded=document.createElement('details');excluded.className='generation-excluded';
      excluded.append(textElement('summary',`Filtered recipes (${excludedCandidates.length})`),textElement('p','These candidates did not meet the original hard conditions. They are not recommendations.','field-help'));
      for(const assessment of excludedCandidates){
        const recipe=recipes.get(assessment.recipe_id);if(!recipe)continue;
        const row=document.createElement('article');row.className='excluded-recipe-row';
        const title=textElement('button',recipe.name,'recipe-title');title.type='button';title.addEventListener('click',()=>loadRecipeDetail(recipe.recipe_id,title,recipe));row.append(title);
        const failedChecks=(assessment.checks||[]).filter(check=>!check.alternative_not_needed&&(check.decision==='fail'||(check.role==='required'&&check.status==='not_matched')||(check.role==='excluded'&&check.status==='matched')));
        for(const check of failedChecks){
          row.append(textElement('p',`${check.role==='excluded'?'Excluded condition violated':'Required condition not met'}: ${check.category}`,'excluded-recipe-reason'));
          if(check.reason)row.append(textElement('p',check.reason));
          if(check.evidence?.length)row.append(textElement('p','Ingredient evidence: '+ingredientEvidenceText(check),'field-help'));
        }
        if(!failedChecks.length)row.append(textElement('p','Did not meet hard category conditions: '+(assessment.violations||[]).join(', '),'excluded-recipe-reason'));
        excluded.append(row);
      }
      research.append(excluded);
    }
    if(data.pending_recipe_ids?.length) {
      const pending=document.createElement('section'); pending.className='generation-pending';
      pending.append(textElement('h3','Needs confirmation'),textElement('p','These recipes are not counted as recommendations because their hard requirements could not be confirmed.','field-help'));
      for(const id of data.pending_recipe_ids) {
        const recipe=recipes.get(id), assessment=assessments.get(id); if(!recipe || !assessment) continue;
        const button=textElement('button',recipe.name,'recipe-title'); button.type='button'; button.addEventListener('click',()=>loadRecipeDetail(id,button,recipe)); pending.append(button);
        for(const check of assessment.checks.filter(c=>['required','excluded'].includes(c.role)&&c.status==='unknown'&&!c.alternative_not_needed)) pending.append(textElement('p',`${conditionLabel(check)}: ${check.reason}${check.evidence?.length?' · Evidence: '+ingredientEvidenceText(check):''}`,'search-warning'));
      }
      research.append(pending);
    }
    if(data.not_checked_recipe_ids?.length){
      const section=document.createElement('details');section.className='generation-not-checked';section.append(textElement('summary',`${uncheckedLabel(data)} (${data.not_checked_recipe_ids.length})`),textElement('p',targetReached(data)?'The qualified target was reached. These lower-ranked candidates were not needed; their eligibility is unconfirmed and they are not recommendations.':'These candidates still need checks; they are not qualified recommendations.','field-help'));
      for(const id of data.not_checked_recipe_ids){const recipe=recipes.get(id);if(!recipe)continue;const button=textElement('button',recipe.name,'recipe-title');button.type='button';button.addEventListener('click',()=>loadRecipeDetail(id,button,recipe));section.append(button);}
      research.append(section);
    }
    if(data.eligibility_stats){const stats=data.eligibility_stats;research.append(textElement('p',`Eligibility: ${stats.processed} / ${stats.total} checked · ${stats.batches} batches · target ${stats.target} · stop: ${stats.stop_reason}`,'field-help'));}
    if(data.category_check_ms!=null) research.append(textElement('p',`Eligibility checks: ${(data.category_check_ms/1000).toFixed(2)} s · Summary: ${(data.summary_ms/1000).toFixed(2)} s`,'field-help'));
    for(const [index,call] of (data.model_calls || []).entries()) {
      const entry=document.createElement('details'); entry.append(textElement('summary',`Model call ${index+1} · ${call.phase} · ${(call.elapsed_ms/1000).toFixed(2)} s`));
      appendModelInput(call.model_input,entry); entry.append(generationUsage(call,'This model call'),jsonViewer(call.model_output,'output JSON'),textElement('p',`Tokens: ${JSON.stringify(call.usage || {})} · prompt ${call.prompt_version}`,'field-help')); research.append(entry);
    }
    const details=document.createElement('details');details.append(textElement('summary',`All candidate checks (${data.assessments.length})`));
    for (const assessment of data.assessments) {
      const section=document.createElement('section'); section.append(textElement('h4',`${recipes.get(assessment.recipe_id).name} · ${assessment.status} · ID ${assessment.recipe_id}`));
      for (const check of assessment.checks) section.append(textElement('p',`${conditionLabel(check)}: ${check.status} — ${check.reason}. Evidence: ${ingredientEvidenceText(check)||'None'}`));
      if (!assessment.checks.length) section.append(textElement('p',assessment.status==='not_checked'?(targetReached(data)?'Not needed after the qualified target was reached.':'Required checks have not completed.'):'No hard conditions.'));
      details.append(section);
    }
    research.append(details);
    appendModelInput(data.model_input, research);
    if (data.selection_counts) research.append(textElement('p', `Selection: requested ${data.selection_counts.requested} · available ${data.selection_counts.available} · category-eligible ${data.selection_counts.category_eligible} · model selected ${data.selection_counts.model_selected ?? data.selection_counts.recommended} · filtered ${data.selection_counts.filtered ?? 0} · recommended ${data.selection_counts.recommended}.`, 'field-help'));
    if(data.summary_deduplication?.removed?.length)research.append(textElement('p',`${data.summary_deduplication.removed.length} near-duplicate candidates merged before generation; highest retrieval rank retained.`,'field-help'));
    if(data.recheck_stats)research.append(textElement('p',`Semantic recheck: ${data.recheck_stats.enabled?'on':'off'} · ${data.recheck_stats.checked} reviewed · ${(data.recheck_stats.overturned||[]).length} overturned`,'field-help'));
    const diagnostics=document.createElement('details'); diagnostics.append(textElement('summary','Model & generation diagnostics'),jsonViewer(data, 'output JSON'));
    research.append(textElement('p',`${data.model} · ${data.input_recipe_count} model-input recipes${data.candidate_recipe_count!=null?' · '+data.candidate_recipe_count+' candidates':''} · ${(data.generation_ms/1000).toFixed(2)} s · tokens ${data.usage?.total_tokens ?? 'not returned'} · prompt ${data.prompt_version}`,'field-help'),diagnostics);
    const footer=document.createElement('footer');footer.className='generation-footer';footer.setAttribute('aria-label','Generation research and usage');footer.append(research,usageDisclosure);root.append(footer);
  }
  function checkContext(snapshot){return {query:snapshot.query,intent_snapshot:snapshot.intent,retrieval_snapshot:snapshot.body,
    recipe_ids:snapshot.data.generation_candidate_ids||snapshot.data.results.map(r=>String(r.document_id||r.recipe_id)),
    retrieval_trace:{relaxation:snapshot.data.relaxation?{status:snapshot.data.relaxation.status,selected_plan:snapshot.data.relaxation.selected_plan}:null,bm25_fallback:snapshot.data.bm25_fallback,branch_filters:snapshot.data.branch_filters,generation_candidate_levels:snapshot.data.generation_candidate_levels}};}
  async function readStageResponse(response,onProgress){
    if(!response.headers.get('content-type')?.includes('text/event-stream'))return response.json();
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result;
    while(true){const chunk=await reader.read();if(chunk.done)break;buffer+=decoder.decode(chunk.value,{stream:true});let boundary;
      while((boundary=buffer.indexOf('\n\n'))>=0){const event=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);const line=event.split('\n').find(v=>v.startsWith('data: '));if(!line)continue;const value=JSON.parse(line.slice(6));
        if(value.type==='progress')onProgress(value);else if(value.type==='result')result=value.data;else if(value.type==='error')result={failed:true,detail:value.detail};}}
    if(!result)throw new Error('Recipe Check ended without a complete result. Retry manually.');return result;
  }
  function renderCheckGroups(root,data,local,records){
    const groups=document.createElement('div');groups.className='check-outcome-groups';
    const labels={near_miss:'close alternatives',pass:local?'locally qualified':'qualified',fail:'not eligible',unknown:'unconfirmed',not_checked:targetReached(data)?uncheckedLabel(data):local?'pending model checks':'not checked'};
    const help={near_miss:'These alternatives differ on selected relaxed conditions and may also have an unconfirmed dish identity. They are not confirmed recommendations.',pass:'These recipes passed the applicable hard-condition checks. Qualification does not guarantee that every soft preference matches.',fail:'These recipes did not meet the hard conditions. They cannot enter formal recommendations.',unknown:'The completed checks could not confirm these recipes. Review the missing or uncertain evidence below.',not_checked:targetReached(data)?'The target was reached. These lower-ranked candidates were not needed and are not qualified recommendations.':local?'Local review is complete; the necessary model checks have not been run.':'Necessary semantic checks have not been completed. These recipes are not qualified recommendations.'};
    for(const state of ['pass','near_miss','fail','unknown','not_checked']){
      const rows=(data.assessments||[]).filter(a=>a.status===state).sort((a,b)=>state==='near_miss'?(a.deviations?.length||0)-(b.deviations?.length||0):0),group=document.createElement('details');group.className='check-outcome-group';group.dataset.outcome=state;
      const summary=document.createElement('summary');summary.append(textElement('span',String(data.constraint_counts?.[state]??rows.length),'check-outcome-count'),document.createTextNode(' '),textElement('span',labels[state],'check-outcome-label'));group.append(summary);
      const body=document.createElement('div');body.className='check-outcome-body';body.append(textElement('p',help[state],'field-help'));
      if(!rows.length)body.append(textElement('p','No recipes in this group.','field-help'));
      for(const a of rows){
        const recipe=records.get(a.recipe_id),entry=document.createElement('article');entry.className='check-recipe';entry.dataset.recipeId=a.recipe_id;
        const heading=document.createElement('h4'),view=document.createElement('button');view.type='button';view.className='check-recipe-link';view.textContent=recipe?.name||'Recipe';view.addEventListener('click',()=>globalThis.loadRecipeDetail?.(a.recipe_id,view,recipe));heading.append(view);
        const header=document.createElement('div');header.className='check-recipe-header';header.append(heading,textElement('span',`Recipe ID: ${a.recipe_id}`,'check-recipe-id'));entry.append(header);
        const evidence=document.createElement('details');evidence.className='check-recipe-evidence';
        const total=(a.checks||[]).length,decisive=(a.checks||[]).filter(c=>!c.waived&&(c.decision==='fail'||c.decision==='unknown'));
        const preview=decisive[0]||a.checks?.[0];
        if(preview)entry.append(textElement('p',`${conditionLabel(preview)} — ${preview.waived?'Waived for relaxed recall; the other requirements still apply.':preview.reason||preview.decision}`,'check-recipe-preview'));
        evidence.append(textElement('summary',`View condition details · ${total} ${total===1?'check':'checks'}`));
        const content=document.createElement('div');content.className='check-recipe-evidence-body';evidence.append(content);entry.append(evidence);
        if(a.deviations?.length)for(const deviation of a.deviations)content.append(textElement('p',deviation.reason,'search-warning'));
        if(state==='not_checked'){
          const stop=data.eligibility_stats?.stop_reason;
          const reason=local?'Model checks have not started. Click Check candidates to run them.':targetReached(data)?'Checking stopped because the qualified-candidate target was reached.':a.reason||'The required semantic check has not run.';
          content.append(textElement('p',reason,'check-pending-reason'));
        }
        if(a.required_expression)content.append(textElement('p',`Required logic: ${globalThis.RecipeRequired?.format(a.required_expression)||''} · ${a.required_group_status||'pending'}`,'field-help'));
        if(!(a.checks||[]).length)content.append(textElement('p',state==='pass'?'No hard conditions require checking.':a.reason||'No per-condition evidence was returned.','field-help'));
        const identityChecks=(a.checks||[]).filter(c=>['dish_name','dish_type'].includes(c.kind));
        const identity=document.createElement('div');identity.className='check-dish-identity';
        if(identityChecks.length){identity.append(textElement('h5','Dish identity'));if(identityChecks.length>1)identity.append(textElement('p','Dish name and type describe the same target; ingredients are separate only when explicitly requested.','field-help'));content.append(identity);}
        for(const c of a.checks||[]){
          const check=document.createElement('div');check.className='check-condition';check.dataset.decision=c.decision||'unknown';
          const pending=state==='not_checked'&&c.semantic_required&&c.decision==='unknown';
          const verdict=c.waived?'Waived for relaxed recall':c.alternative_not_needed?'Alternative not needed for the required group':pending?'Pending semantic check':({pass:'Passed',fail:'Not satisfied',unknown:'Unconfirmed'}[c.decision]||'Decision not provided');
          check.append(textElement('p',exclusionMet(c)?conditionLabel(c):`${conditionLabel(c)}${c.kind==='ingredient'||c.kind==='category'?' · Core: '+(c.core?'yes':'no'):''} · ${verdict}`,'check-condition-title'));
          if(c.waiver_reason)check.append(textElement('p',c.waiver_reason,'search-warning'));
          if(c.reason)check.append(textElement('p',c.reason));
          check.append(textElement('p',`Evidence: ${ingredientEvidenceText(c)||'No recorded evidence returned'}`,'field-help'),textElement('p',`Source: ${c.source==='model'?'Model check':c.source==='local'?'Local check':'Not specified'}`,'field-help'));
          (identityChecks.includes(c)?identity:content).append(check);
        }
        body.append(entry);
      }
      group.append(body);groups.append(group);
    }
    const card=document.createElement('section');card.className='check-results-card';card.setAttribute('aria-label','Candidate qualification results');
    const header=document.createElement('div');header.className='check-results-heading';header.append(textElement('h3','Candidate results'),textElement('p','Expand a group to review recipes and their condition checks.','field-help'));card.append(header,groups);root.append(card);
  }
  function renderChecks(data,local){
    const root=document.getElementById('check-output');root.replaceChildren();
    for(const item of data.ingredient_relaxation_notes||[])root.append(textElement('p',item.message,'field-help'));
const counts=data.constraint_counts||{};
    const countText=local?`Locally qualified ${counts.pass||0}${counts.near_miss?' · '+counts.near_miss+' close alternatives':''} · ${targetReached(data)?'Not needed (target reached)':'Pending model checks'} ${counts.not_checked||0} · Not eligible ${counts.fail||0} · Unconfirmed ${counts.unknown||0}`:`${counts.pass||0} qualified · ${counts.near_miss?counts.near_miss+' close alternatives · ':''} ${counts.fail||0} not eligible · ${counts.unknown||0} unconfirmed · ${counts.not_checked||0} ${uncheckedLabel(data)}`;
    localSummary.textContent=countText;localSummary.hidden=false;
    if(data.failed_batches?.length){
      const failures=document.createElement('section');failures.className='check-batch-failures';failures.append(textElement('h3','Incomplete checks'),textElement('p','Successful checks have been retained. Retry only the affected recipes; no batch is retried automatically.','field-help'));
      for(const batch of data.failed_batches){
        const item=document.createElement('div');item.className='check-batch-failure';item.append(textElement('p',`${batch.recipe_ids.length} recipes not checked · ${batch.batch_id}`));
        const reasons=document.createElement('details');reasons.append(textElement('summary','View failure reasons'));for(const error of batch.errors||[])reasons.append(textElement('p',error,'field-help'));item.append(reasons);
        const retry=document.createElement('button');retry.type='button';retry.className='retry-check-batch';retry.textContent='Retry this batch';retry.addEventListener('click',()=>runChecks(false,{run_id:data.check_run_id,batch_id:batch.batch_id}));item.append(retry);failures.append(item);
      }
      root.append(failures);
    }
    const records=new Map((data.recipes||[]).map(r=>[r.recipe_id,r]));
    renderCheckGroups(root,data,local,records);
    const footer=document.createElement('section');footer.className='check-debug-footer';footer.setAttribute('aria-label','Research diagnostics');
    const stats=data.eligibility_stats||{},stops={enough_qualified_candidates:'Qualified target reached',candidate_pool_exhausted:'Candidate pool exhausted',batch_failures:'Some batches need retry',near_miss_target_reached:'Close alternative target reached'};const runStats=textElement('p',`Target ${stats.target} · Model calls ${(data.model_calls||[]).length} · ${local?'Local checks only':data.cache_hit?'Cached result · no new model calls':`Stop: ${stops[stats.stop_reason]||stats.stop_reason}`}`,'field-help');
    if(!local){const usage=document.createElement('details');usage.className='check-usage-disclosure';usage.append(textElement('summary','Token usage & estimated cost'),generationUsage(data,'This Recipe Check'));if(data.current_attempt_usage&&data.new_model_call_count<(data.model_calls||[]).length)usage.append(generationUsage(data.current_attempt_usage,'Latest attempt only'));footer.append(usage);}
    const research=document.createElement('details');research.className='check-research';research.append(textElement('summary','Research details · checks, model input & diagnostics'),runStats);
    for(const warning of data.warnings||[])research.append(textElement('p',warning,'search-warning'));
    for(const call of (data.cache_hit?data.original_check_usage?.model_calls:data.model_calls)||[]){const detail=document.createElement('details');detail.append(textElement('summary',`${data.cache_hit?'Earlier model check · cached diagnostics':'Model check'} · ${(call.recipe_ids||[]).length} recipes`),jsonViewer(call.model_input,'input JSON'),jsonViewer(call.model_output,'output JSON'),generationUsage(call,'This model call'));research.append(detail);}
    research.append(jsonViewer(data,'output JSON'));footer.append(research);root.append(footer);
  }
  async function runChecks(local=false,retry=null){
    if(!retrieval?.data.results.length||(!local&&checking))return;
    checkController?.abort();const controller=new AbortController();checkController=controller;const ticket=++checkTicket,version=revision;
    const snapshot=clone(retrieval),context=checkContext(snapshot);checking=true;checkedPool=null;
    const forward=handoffs.retrieval.querySelector('button');if(globalThis.RecipeActionIcon)RecipeActionIcon(forward,'next','Review & check candidates');else forward.textContent='Review & check candidates';clearGenerated('Check candidates first.');buttons.generation.disabled=true;handoffs.check.hidden=true;
    const action=document.getElementById('check-candidates');action.disabled=true;
    if(!retry)document.getElementById('check-output').replaceChildren();
    document.querySelectorAll('.retry-check-batch').forEach(button=>button.disabled=true);
    if(!local)status('check','Processing');
    document.getElementById('check-status').textContent=local?'Running local checks · no model calls…':'Checking candidate requirements…';
    const deadline=setTimeout(()=>controller.abort(),420000);
    try{
      const response=await fetch(`/content/eligibility/${document.getElementById('check-model').value}${local?'':'?stream=true'}`,{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',signal:controller.signal,body:JSON.stringify({...context,local_only:local,...(retry?{retry_run_id:retry.run_id,retry_batch_ids:[retry.batch_id]}:{})})});
      const data=await readStageResponse(response,value=>{if(ticket===checkTicket&&version===revision)document.getElementById('check-status').textContent=`Checking candidates: ${value.completed} / ${value.total} · batches ${value.batch||'in progress'}`;});
      if(ticket!==checkTicket||version!==revision||checkController!==controller)return;
      if(!response.ok||data.failed){const output=document.getElementById('check-output');if(retry)output.append(jsonViewer(data.detail,'retry failure JSON'));else output.replaceChildren(jsonViewer(data.detail,'output JSON'));throw new Error(data.detail?.message||'Recipe Check failed. Retry manually.');}
      if(JSON.stringify(data.generation_context)!==JSON.stringify({query:context.query,recipe_ids:context.recipe_ids}))throw new Error('Recipe Check response does not match this request. Results discarded.');
      if(data.schema_version&&data.schema_version!=='recipe-generation-v11')throw new Error('The server uses an older Recipe Check schema. Restart the backend and check candidates again.');
      renderChecks(data,local&&!data.auto_completed);
      if(!data.partial&&(!local||data.eligibility_id)){checkedPool={...data,context};const ready=Boolean(data.qualified_recipe_ids?.length||data.near_miss_recipe_ids?.length);buttons.generation.disabled=!ready;document.getElementById('generate-content').disabled=!ready;handoffs.check.hidden=!ready;handoffs.check.querySelector('span').textContent=`${data.constraint_counts.pass} qualified · ${data.constraint_counts.near_miss?data.constraint_counts.near_miss+' close alternatives · ':''} Top ${data.qualified_recipe_ids.length}${data.near_miss_recipe_ids?.length?' + '+data.near_miss_recipe_ids.length+' close alternatives':''} selected for generation`;status('check','Complete',data.check_ms);clearGenerated(ready?'Not run':'No qualified candidates');}
      if(data.partial)status('check','Partial',data.check_ms);
      if(data.auto_completed){const forward=handoffs.retrieval.querySelector('button');if(globalThis.RecipeActionIcon)RecipeActionIcon(forward,'next','Continue to generation');else forward.textContent='Continue to generation';handoffs.retrieval.querySelector('span').textContent=`${data.constraint_counts.pass} qualified locally · Top ${data.qualified_recipe_ids.length}${data.near_miss_recipe_ids?.length?' + '+data.near_miss_recipe_ids.length+' close alternatives':''} selected for generation`; }
      document.getElementById('check-status').textContent=data.partial?'Some checks could not finish. Completed results are saved; retry the failed batches below before generation.':local&&!data.eligibility_id?'Local checks complete. Click Check candidates to finish model checks.':(data.qualified_recipe_ids.length||data.near_miss_recipe_ids?.length)?'Recipe Check complete. Continue to generation.':'No confirmed candidates. Review the checks or revise your request.';
    }catch(error){if(ticket!==checkTicket||version!==revision)return;status('check','Failed');document.getElementById('check-status').textContent=error.name==='AbortError'?'Recipe Check timed out. Retry manually.':error.message;}
    finally{clearTimeout(deadline);if(ticket===checkTicket&&version===revision){checking=false;action.disabled=!retrieval?.data.results.length;checkController=null;document.querySelectorAll('.retry-check-batch').forEach(button=>button.disabled=false);}}
  }
  document.getElementById('check-candidates').addEventListener('click',()=>runChecks(false));
  document.getElementById('generate-content').addEventListener('click',async () => {
    if (!(checkedPool?.qualified_recipe_ids?.length||checkedPool?.near_miss_recipe_ids?.length) || generating) return;
    const snapshot=clone({query:retrieval.query, intent:retrieval.intent, body:retrieval.body, data:retrieval.data}), generationRevision=revision;
    const requestedIds = snapshot.data.generation_candidate_ids || snapshot.data.results.map(recipe=>String(recipe.document_id||recipe.recipe_id));
    const requestContext = {query:snapshot.query, recipe_ids:requestedIds};
    clearGenerated('Processing'); generating=true; generationController=new AbortController();
    const controller=generationController;
    const generate=document.getElementById('generate-content'); generate.disabled=true;
    const deadline=setTimeout(()=>controller.abort(),420000);
    try {
      const response=await fetch(`/content/generate/${document.getElementById('generation-model').value}?stream=true`,{
        method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,cache:'no-store',
        body:JSON.stringify({eligibility_id:checkedPool.eligibility_id,context:checkedPool.context,recheck:document.getElementById('generation-recheck').checked})});
      let data;
      if(response.headers.get('content-type')?.includes('text/event-stream')) {
        const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
        while(true) {
          const chunk=await reader.read(); if(chunk.done) break;
          if(generationRevision!==revision || generationController!==controller) {await reader.cancel(); return;}
          buffer+=decoder.decode(chunk.value,{stream:true});
          let boundary;
          while((boundary=buffer.indexOf('\n\n'))>=0) {
            const event=buffer.slice(0,boundary); buffer=buffer.slice(boundary+2);
            const line=event.split('\n').find(value=>value.startsWith('data: ')); if(!line) continue;
            const value=JSON.parse(line.slice(6));
            if(value.type==='progress') {
              const counts=value.counts;
              document.getElementById('generation-status').textContent=value.phase==='summary'?'Writing recommendations from confirmed candidates…':`Checking hard conditions: ${value.completed} / ${value.total}${counts?` · ${counts.pass} passed · ${counts.fail} not eligible · ${counts.unknown} unconfirmed`:''}`;
            } else if(value.type==='result') data=value.data;
            else if(value.type==='error') data={detail:value.detail,failed:true};
          }
        }
        if(!data) throw new Error('Generation ended before a complete result was received. Retry manually.');
      } else data=await response.json();
      if (generationRevision !== revision || generationController !== controller) return;
      if (!response.ok || data.failed) {
        document.getElementById('generation-output').append(generationUsage(data.detail || {},'Calls recorded before failure'));
        if(data.detail?.code==='generation_context_too_large') document.getElementById('generation-output').append(textElement('p','Input exceeded the local context limit. This prepared request was not sent to the model.','search-warning'));
        appendModelInput(data.detail?.model_input);
        for(const call of data.detail?.model_calls || []) {appendModelInput(call.model_input); document.getElementById('generation-output').append(jsonViewer(call.model_output,'batch output JSON'));}
        document.getElementById('generation-output').append(jsonViewer(data.detail, 'output JSON'));
        if(data.detail?.model_output) document.getElementById('generation-output').append(jsonViewer(data.detail.model_output, 'raw model output'));
        throw new Error(data.detail?.message||'Generation failed. Review diagnostics and retry.');
      }
      if (JSON.stringify(data.generation_context) !== JSON.stringify(requestContext)) {
        throw new Error('Generation response does not match this request. Restart the server, refresh the page and generate again. Previous results were discarded.');
      }
      if (data.recipes.some(recipe => !requestedIds.includes(String(recipe.recipe_id))) || data.recommendations.some(item => !requestedIds.includes(String(item.recipe_id)))) {
        throw new Error('Generation returned recipes outside the current retrieval. Results were discarded.');
      }
      if(data.schema_version && data.schema_version!=='recipe-generation-v11')throw new Error('The server uses an older Recipe Check schema. Restart the backend and generate again.');
      if(data.recommendations.some(item=>!data.assessments.some(a=>a.recipe_id===item.recipe_id&&a.status==='pass')))throw new Error('A recommendation lacks confirmed hard-condition eligibility. Results were discarded; review the backend diagnostics.');
      buttons.generation.disabled=false;renderGenerated(data, snapshot); status('generation','Complete',data.generation_ms); document.getElementById('generation-status').textContent='Generated from recorded recipe data. Unconfirmed category constraints are listed separately.';
    } catch(error) {
      if (generationRevision !== revision || generationController !== controller) return;
      status('generation','Failed'); document.getElementById('generation-status').textContent=error.name==='AbortError'?'Generation timed out. Retry manually.':error.message;
    } finally {
      clearTimeout(deadline);
      if (generationRevision === revision && generationController === controller) {generating=false;generate.disabled=false;generationController=null;}
    }
  });
})();
