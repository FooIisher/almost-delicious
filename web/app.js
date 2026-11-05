const form = document.querySelector('#search-form');
const button = document.querySelector('#submit-button');
const progress = document.querySelector('#progress');
const results = document.querySelector('#results');
const empty = document.querySelector('#empty');
const detailPanel = document.querySelector('#detail-panel');
const template = document.querySelector('#card-template');
const split = value => value.split(',').map(item => item.trim()).filter(Boolean);
let detailTrigger = null;

function updateScopeUI() {
  const scope=false;
  document.getElementById('scope-settings').hidden=!scope;
  const query=document.getElementById('query');
  const mode=document.getElementById('mode').value;
  query.required=!scope && mode!=='vector';query.disabled=scope || mode==='vector';
  document.getElementById('query-label').textContent=scope?'BM25 query · Not used in Label scope':'BM25 query';
  const vector=document.getElementById('vector-query');vector.required=mode!=='bm25';vector.disabled=mode==='bm25';
}
globalThis.RecipeScopeUI={update:updateScopeUI};
document.getElementById('retrieval-strategy').addEventListener('change',updateScopeUI);

function updateRetrievalSettings() {
  updateScopeUI();
  const mode = document.querySelector('#mode').value;
  document.querySelectorAll('.retrieval-settings [data-mode]').forEach(field => {
    const visible = field.dataset.mode.split(' ').includes(mode);
    field.hidden = !visible;
    field.querySelectorAll('input, select').forEach(input => { input.disabled = !visible; });
  });
  const help = document.querySelector('#retrieval-help');
  help.textContent = mode === 'hybrid'
    ? 'Each candidate count must be at least Results. RRF contribution = boost / (k + rank); boosts must be greater than zero.'
    : mode === 'vector' ? 'kNN exploration candidates must be at least Vector candidates.' : '';
  help.hidden = mode === 'bm25';
}
document.querySelector('#mode').addEventListener('change', updateRetrievalSettings);
updateRetrievalSettings();

const milliseconds = value => value === null || value === undefined ? '—' : `${Number(value).toFixed(2)} ms`;

function setLoading(loading, mode = 'hybrid') {
  button.disabled = loading;
  const active=globalThis.RecipeRetrievalTabs?.active || mode;
  const label=loading ? `Running ${active==='hybrid'?'Hybrid':active.toUpperCase()}` : active==='hybrid'?'Refresh Hybrid':`Run ${active.toUpperCase()}`;
  if (globalThis.RecipeActionIcon) RecipeActionIcon(button,'search',label,loading);
  else button.innerHTML = loading ? 'Searching…' : 'Retrieval <span>→</span>';
  if (!loading) return;
  globalThis.RecipeRetrievalFlow?.start(mode,{execution:document.getElementById('execution').value,include:split(document.getElementById('include').value),exclude:split(document.getElementById('exclude').value),expression:globalThis.RecipeRequired?.parse(document.getElementById('required-expression').value),strategy:document.getElementById('retrieval-strategy').value,meal:split(document.getElementById('scope-meal-types').value),cuisine:split(document.getElementById('scope-cuisines').value)});
  progress.classList.remove('hidden');
  for (const step of ['bm25', 'vector', 'rrf']) {
    const enabled = mode === 'hybrid' || mode === step;
    document.querySelector(`#${step}-time`).textContent = enabled ? 'Waiting' : 'Skipped';
  }
  document.querySelector('#total-time').textContent = 'Running';
  for (const id of ['embedding-time', 'vector-query-time', 'bm25-query-time', 'backend-time', 'e2e-time']) {
    document.getElementById(id).textContent = '—';
  }
  progress.querySelectorAll('.dot').forEach(dot => dot.classList.remove('active'));
}

function updateProgress(event) {
  globalThis.RecipeRetrievalFlow?.update(event);
  const row = progress.querySelector(`[data-step="${event.step}"]`);
  if (!row) return;
  const time = row.querySelector('b');
  row.querySelector('.dot').classList.toggle('active', event.status === 'running');
  if (event.status === 'running') time.textContent = 'Running…';
  else if (event.status === 'complete') time.textContent = milliseconds(event.elapsed_ms);
  else if (event.status === 'skipped') time.textContent = 'Skipped';
  else time.textContent = `${event.status === 'timeout' ? 'Timed out' : 'Failed'} (${milliseconds(event.elapsed_ms)})`;
}

function showTimings(data, browserElapsed) {
  for (const [id, key] of Object.entries({
    'embedding-time': 'query_embedding_ms', 'vector-query-time': 'vector_query_ms',
    'bm25-query-time': 'bm25_query_ms', 'total-time': 'search_total_ms',
    'backend-time': 'backend_request_ms',
  })) document.getElementById(id).textContent = milliseconds(data.timings[key]);
  for (const step of ['bm25', 'vector']) {
    if (data.branches[step]) updateProgress({step, ...data.branches[step]});
  }
  updateProgress({step: 'rrf', status: data.rrf ? 'complete' : 'skipped', elapsed_ms: data.timings.rrf_ms});
  document.querySelector('#e2e-time').textContent = milliseconds(browserElapsed);
}

async function readSearchStream(response, isCurrent = () => true) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result;
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split('\n\n'); buffer = frames.pop();
    for (const frame of frames) {
      const dataLine = frame.split('\n').find(line => line.startsWith('data: '));
      if (!dataLine) continue;
      const event = JSON.parse(dataLine.slice(6));
      if (event.type === 'progress' && isCurrent()) updateProgress(event);
      if (event.type === 'error') throw new Error(`${event.message}\n${event.exception_type}: ${event.exception}`);
      if (event.type === 'result') result = event;
    }
    if (done) break;
  }
  if (!result) throw new Error('Search stream ended before a result was returned.');
  return result;
}

function activeFilterChips(request) {
  const labels = {
    less_30: 'Total time: <30 min',
    '30_60': 'Total time: 30–60 min',
    '60_120': 'Total time: 1–2 h',
    '120_180': 'Total time: 2–3 h',
    more_180: 'Total time: >3 h',
  };
  const chips = [
    ...(request.numeric_filters || []).map(condition => `${{total_time:'Total time', calories:'Calories', protein:'Protein'}[condition.field]} ${{lt:'<',lte:'≤',gt:'>',gte:'≥',eq:'='}[condition.operator]} ${condition.value} ${condition.field === 'total_time' ? 'min' : condition.field === 'calories' ? 'kcal / serving' : 'g / serving'}`),
    ...((request.scope_meal_types || []).length?[`Meal scope: ${request.scope_meal_types.join(' / ')}`]:[]),
    ...((request.scope_cuisines || []).length?[`Cuisine scope: ${request.scope_cuisines.join(' / ')}`]:[]),
    ...((request.labels || []).length ? [`Labels (any): ${request.labels.join(', ')}`] : []),
    ...(request.required_expression?[`Required: ${globalThis.RecipeRequired?.format(request.required_expression)}`]:request.include_ingredients?.length?[`Required (any): ${request.include_ingredients.join(' / ')}`]:[]),
    ...((request.category_required||[]).length?[`Required categories · final check: ${request.category_required.join(' / ')}`]:[]),
    ...((request.category_excluded||[]).length?[`Excluded categories · final check: ${request.category_excluded.join(', ')}`]:[]),
    ...(request.exclude_ingredients || []).map(item => `Exclude: ${item}`),
    request.cook_time ? labels[request.cook_time] : null,
    request.max_total_time_minutes !== null && request.max_total_time_minutes !== undefined
      ? `Max total: ${request.max_total_time_minutes} min` : null,
    request.max_calories !== null && request.max_calories !== undefined
      ? `Max calories: ${request.max_calories} / serving` : null,
  ].filter(Boolean);
  if (!chips.length) return '';
  return `<div class="active-filters" aria-label="Original hard conditions"><span>Original conditions</span>${chips.map(chip => `<span class="filter-chip">${escapeHtml(chip)}</span>`).join('')}</div>`;
}

function renderHighlight(value) {
  return escapeHtml(value).replaceAll('&lt;em&gt;', '<mark>').replaceAll('&lt;/em&gt;', '</mark>');
}

function lexicalEvidence(recipe) {
  const fieldLabels = {name: 'Title', keywords: 'Tags', ingredients: 'Ingredients', extract_ingredients: 'Mentioned in instructions', description: 'Description'};
  const highlights = recipe.match_highlights || {};
  const evidence = Object.entries(highlights)
    .filter(([, fragments]) => Array.isArray(fragments) && fragments.length)
    .slice(0, 2)
    .map(([field, fragments]) => `<span><b>${fieldLabels[field] || field}:</b> ${renderHighlight(fragments[0])}</span>`);
  return evidence.length
    ? `<b>Why matched · lexical:</b> ${evidence.join('<span class="why-separator" aria-hidden="true">·</span>')}`
    : '<b>Why matched · lexical:</b> matching analyzed query terms';
}

function vectorEvidence(recipe) {
  const similarity = Number(recipe.semantic_similarity);
  const value = Number.isFinite(similarity) ? similarity.toFixed(4) : '—';
  return `<b>Why matched · semantic:</b> cosine similarity <mark>${value}</mark>`;
}

function showResults(data, request = {}) {
  const totalPrefix = data.match_result_size?.relation === 'gte' ? '≥' : '';
  const matched = `${totalPrefix}${data.match_result_size?.value ?? data.result_count}`;
  const resultSummary = data.mode === 'hybrid'
    ? `Candidate union: ${data.candidate_counts.union} · BM25 ${data.candidate_counts.bm25} / Vector ${data.candidate_counts.vector}`
    : data.mode === 'vector' ? `Vector candidates: ${data.result_count}` : `${data.retrieval_strategy==='label_scope'?'Label scope':'Lexical'} matches: ${matched}`;
  const status = data.mode === 'hybrid' && data.effective_mode !== 'hybrid'
    ? `${data.effective_mode.toUpperCase()} ONLY · degraded` : data.mode === 'hybrid' ? 'HYBRID · RRF' : data.mode.toUpperCase();
  results.innerHTML = `${activeFilterChips(data.effective_filters || request)}<p class="result-summary"><strong>${escapeHtml(resultSummary)}</strong> · showing ${data.result_count} · ${escapeHtml(status)} · ${escapeHtml(data.execution)} · ${data.from_hybrid_run ? "recall " + milliseconds(data.timings[data.mode+"_recall_ms"]) + " · from latest Hybrid run" : "search " + milliseconds(data.timings.search_total_ms)}</p>`;
  for (const warning of data.warnings || []) {
    results.innerHTML += `<p class="search-warning" role="status">${escapeHtml(warning)}</p>`;
  }
  if (!data.results.length) results.innerHTML += '<p class="empty">No recipes matched these filters. Try broadening your ingredients.</p>';
  if (data.preferences) {
    results.innerHTML += `<details class="ranking-run-details"><summary>Retrieval and ranking configuration</summary><strong>Ranking preferences · λ ${data.preferences.preference_lambda}</strong>${Object.entries(data.preferences).filter(([k,v]) => Array.isArray(v) && v.length).map(([k,v]) => `<p>${k === 'preference_avoid' ? 'Penalty' : 'Boost'} · ${escapeHtml(k.replace('preference_', ''))}: ${escapeHtml(v.join(', '))} · weight ${data.preferences['preference_weight_' + k.replace('preference_', '')] ?? 1}</p>`).join('')}<p>Rating boost: ${data.preferences.rating_boost ?? 0} · Rating 3–5 × rating / 5; below 3 or missing earns no bonus.</p><p>Reranking: ${milliseconds(data.timings.preference_rerank_ms)}.</p></details>`;
  }
  data.results.forEach(recipe => {
    const node = template.content.cloneNode(true);
    const image = node.querySelector('img'); const wrapper = node.querySelector('.recipe-image');
    const url = recipe.display_image_url;
    const placeholder = recipe.fallback_image_url || '/assets/recipe-icons/default.svg';
    image.src = url || placeholder;
    image.alt = recipe.name || 'Recipe image';
    image.title = recipe.image_source || 'display image';
    wrapper.classList.add('has-image');
    RecipeImage.bind(image,node.querySelector('.recipe-card'),recipe);
    node.querySelector('.rank').textContent = `#${recipe.rank}`;
    node.querySelector('.score').textContent = data.mode === 'vector'
      ? `semantic similarity ${Number(recipe.semantic_similarity).toFixed(4)}`
      : data.mode === 'hybrid' ? `Final ${Number(recipe.final_score ?? recipe.rrf_score).toFixed(6)}` : `${data.retrieval_strategy==='label_scope'?'Scope':'BM25'} score ${Number(recipe.score).toFixed(4)}`;
    const title = node.querySelector('.recipe-title');
    const titleHighlight = recipe.match_highlights?.name?.[0];
    title.innerHTML = titleHighlight ? renderHighlight(titleHighlight) : escapeHtml(recipe.name || 'Untitled recipe');
    title.addEventListener('click', () => loadRecipeDetail(recipe.document_id || recipe.recipeid, title));
    node.querySelector('.description').textContent = recipe.description || 'No description available.';
    node.querySelector('.why-matched').innerHTML = data.mode === 'vector' ? vectorEvidence(recipe)
      : data.mode === 'hybrid' && recipe.bm25_rank === null
        ? '<b>Why matched · semantic:</b> recalled by the vector branch'
        : lexicalEvidence(recipe);
    if (data.mode === 'hybrid') {
      node.querySelector('.fusion-details').classList.remove('hidden');
      const evidenceRows = ['bm25', 'vector'].map(branch => {
        const rank = recipe[`${branch}_rank`];
        const contribution = Number(recipe[`${branch}_contribution`]).toFixed(8);
        const formula = rank === null ? 'Not in candidate list' : `${data.rrf[`${branch}_boost`]} / (${data.rrf.k} + ${rank})`;
        return `<tr><th scope="row">${branch === 'bm25' ? 'BM25' : 'Vector'}</th><td>${rank ?? '—'}</td><td>${formula}</td><td>${contribution}</td></tr>`;
      }).join('');
      node.querySelector('.fusion-content').innerHTML = `<table><caption>Recipe ${escapeHtml(recipe.recipe_id)} · weighted RRF</caption><thead><tr><th scope="col">Branch</th><th scope="col">Rank</th><th scope="col">Contribution formula</th><th scope="col">Score</th></tr></thead><tbody>${evidenceRows}</tbody></table><p>Fusion score: <strong>${Number(recipe.rrf_score).toFixed(8)}</strong>. Missing ranks contribute zero. Ties use best branch rank, then recipe ID.</p>`;
    }
    if (data.preferences && recipe.preference_evidence) {
      node.querySelector('.fusion-details').classList.remove('hidden');
      const evidence = recipe.preference_evidence.map(e => {
        if (e.group === 'quick' || e.group === 'easy') {
          const matched = e.match_score > 0;
          const label = e.group === 'quick' ? 'Quick / Fast' : 'Easy';
          const check = (e.checks || [])[0];
          const reason = e.group === 'quick'
            ? `Total time: ${check?.value == null ? 'Missing' : escapeHtml(check.value) + ' min'} · threshold ≤ ${escapeHtml(check?.threshold ?? '—')} min`
            : matched ? 'Matched exact “easy” tag in recipe category or keywords.' : 'No exact “easy” tag found in recipe category or keywords.';
          return `<li><strong>${label} · ${matched ? 'Matched' : 'Not matched'}</strong><br>${reason}<br>Weight ${e.weight} · score ${e.match_score.toFixed(3)} · final score adjustment ${e.final_contribution >= 0 ? '+' : ''}${e.final_contribution.toFixed(4)}</li>`;
        }
        if (e.group === 'healthy') {
          const labels = {proteincontent: 'High protein', sugarcontent: 'Low sugar', fatcontent: 'Low fat', cholesterolcontent: 'Low cholesterol', sodiumcontent: 'Low sodium'};
          const checks = e.checks || [];
          const met = checks.filter(c => c.status === 'met');
          const missing = checks.filter(c => c.status === 'missing');
          const item = c => `<li>${escapeHtml(labels[c.field] || c.field)}: ${escapeHtml(c.value ?? 'Missing')} ${escapeHtml(c.unit)} per serving · threshold ${escapeHtml(c.operator === 'gte' ? '≥' : '≤')} ${escapeHtml(c.threshold)} ${escapeHtml(c.unit)} per serving</li>`;
          const other = checks.filter(c => c.status !== 'met');
          return `<li><strong>Healthy · ${met.length}/${checks.length} criteria met</strong> · weight ${e.weight} · score ${e.match_score.toFixed(3)} · Δ ${e.final_contribution.toFixed(4)}${met.length ? `<ul class="healthy-matches">${met.map(item).join('')}</ul>` : '<p>No criteria met.</p>'}${missing.length ? `<p>${missing.length} nutrient values missing; no points awarded for missing data.</p>` : ''}${other.length ? `<details><summary>Other nutrition criteria (${other.length})</summary><ul>${other.map(c => item(c).replace('</li>', ` · ${escapeHtml(c.status === 'missing' ? 'Missing data' : 'Not met')}</li>`)).join('')}</ul></details>` : ''}</li>`;
        }
        if(['available','prefer','avoid'].includes(e.group))return `<li>${escapeHtml(e.group)}: ${escapeHtml(e.matched.join(', ')||'No match')} · weight ${e.weight} · match ${e.match_score.toFixed(3)} · Δ ${e.final_contribution.toFixed(4)}${(e.checks||[]).flatMap(c=>(c.evidence_sources||[]).map(item=>`<br>${escapeHtml(c.target)}: ${escapeHtml(item.value)} · ${item.field==='extract_ingredients'?'mentioned in instructions (extracted)':'ingredient list'}`)).join('')}</li>`;
        return `<li>${escapeHtml(e.group)}: ${escapeHtml(e.matched.join(', ') || 'No match')} · weight ${e.weight} · match ${e.match_score.toFixed(3)} · Δ ${e.final_contribution.toFixed(4)}${(e.checks || []).map(c => `<br>${escapeHtml(c.field)}: ${escapeHtml(c.value ?? 'missing')} ${escapeHtml(c.unit)} · ${escapeHtml(c.status)} · threshold ${escapeHtml(c.threshold)}`).join('')}</li>`;
      }).join('');
      node.querySelector('.fusion-content').innerHTML += `<p>${data.mode === "hybrid" ? "Pure RRF" : "Original branch"} rank #${recipe.rrf_rank} → final #${recipe.rank}</p><p>${data.mode === "hybrid" ? "Normalized RRF" : "Normalized branch rank"} ${recipe.normalized_rrf.toFixed(4)} + λ ${data.preferences.preference_lambda} × Preference ${recipe.preference_score.toFixed(4)} + Rating bonus ${(recipe.rating_bonus ?? 0).toFixed(4)} = ${recipe.final_score.toFixed(4)}</p><p>Rating ${escapeHtml(recipe.rating_value ?? "missing")} · factor ${recipe.rating_factor ?? 0} × boost ${data.preferences.rating_boost ?? 0} = +${(recipe.rating_bonus ?? 0).toFixed(4)}</p><ul>${evidence || '<li>No ranking preferences</li>'}</ul>`;
      node.querySelector('.why-matched').innerHTML += `<br>${data.mode === "hybrid" ? "Pure RRF" : "Original branch"} #${recipe.rrf_rank} → final #${recipe.rank} · preference adjustment ${(recipe.final_score-recipe.normalized_rrf).toFixed(4)}<ul>${evidence}</ul>`;
    }
    const categories = Array.isArray(recipe.recipecategory) ? recipe.recipecategory : [recipe.recipecategory];
    const tags = [...new Set([...categories, ...(recipe.keywords || [])].filter(Boolean))];
    node.querySelector('.tags').innerHTML = tags.map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('');
    const ingredients = recipe.ingredients || [];
    const ingredientLine = node.querySelector('.ingredients');
    ingredientLine.innerHTML = ingredients.length
      ? `<strong class="ingredient-count">${ingredients.length} ingredients</strong><span class="ingredient-list"> · ${ingredients.map(ingredient => escapeHtml(String(ingredient))).join(', ')}</span>`
      : '<strong class="ingredient-count">Ingredients</strong><span class="ingredient-list"> · Not available</span>';
    const rating = Number(recipe.aggregatedrating);
    const timeDetails = [
      Number.isFinite(rating) && rating > 0 ? `<span class="rating">★ ${rating.toFixed(1)}</span>` : null,
      recipe.prep_time_minutes ? `<span>Prep ${recipe.prep_time_minutes} min</span>` : null,
      recipe.cook_time_minutes ? `<span>Cook ${recipe.cook_time_minutes} min</span>` : null,
      recipe.total_time_minutes ? `<span>Total ${recipe.total_time_minutes} min</span>` : null,
    ].filter(Boolean);
    node.querySelector('.details').innerHTML = timeDetails.join('<span class="detail-separator" aria-hidden="true">·</span>') || '<span>Time not available</span>';
    if (recipe.bm25_matched_queries?.length) {
      node.querySelector('.why-matched').textContent += ` BM25 boosts matched: ${recipe.bm25_matched_queries.join(', ')}.`;
    }
    const card = node.querySelector('.recipe-card');
    const copy = node.querySelector('.card-copy');
    const details = node.querySelector('.fusion-details');
    const detailContent = node.querySelector('.fusion-content');
    details.classList.remove('hidden'); details.querySelector('summary').textContent = 'Recipe & ranking details';
    for (const selector of ['.ingredients','.why-matched']) detailContent.append(node.querySelector(selector));
    if(recipe.extract_ingredients?.length){const extracted=document.createElement('p');extracted.className='field-help instruction-ingredients';extracted.textContent='Mentioned in instructions (extracted): '+recipe.extract_ingredients.join(', ');detailContent.append(extracted);}
    const tagGroups = node.querySelector('.tags'); tagGroups.replaceChildren();
    for (const [label, values] of [['Category', categories], ['Keywords', recipe.keywords || []]]) {
      const row = document.createElement('div'); row.className = 'recipe-tag-row';
      const heading = document.createElement('span'); heading.className = 'recipe-tag-label'; heading.textContent = label;
      const items = document.createElement('div'); items.className = 'recipe-tag-values';
      const entries = [...new Set((Array.isArray(values) ? values : [values]).filter(Boolean))];
      for (const value of entries) {const chip = document.createElement('span'); chip.className = 'tag'; chip.textContent = String(value); items.append(chip);}
      if (!entries.length) {const missing = document.createElement('span'); missing.className = 'recipe-tag-missing'; missing.textContent = 'Not recorded'; items.append(missing);}
      row.append(heading, items); tagGroups.append(row);
    }
    const timeChecks=recipe.time_constraint_matches || [];
    const timeLabels=timeChecks.map(c=>`Total time ${c.value ?? 'not recorded'} ${c.unit} · requested ${{lt:'<',lte:'≤',gt:'>',gte:'≥',eq:'='}[c.operator]} ${c.threshold} ${c.unit} · ${c.status==='met'?'Time requirement met':c.status==='missing'?'Unconfirmed':'Time requirement not met'}`);
    if(timeLabels.length){const list=document.createElement('p');list.className='time-constraint-evidence';list.textContent=timeLabels.join(' · ');detailContent.append(list);}
    const matches=(recipe.preference_evidence || []).filter(e=>e.match_score>0 && e.group!=='avoid');
    const reasons=matches.map(e=>(e.group==='healthy' ? 'Nutrition criteria' : e.group.replaceAll('_',' ')) + (e.matched?.length ? ': '+e.matched.join(', ') : ' matched'));
    const reason=document.createElement('p'); reason.className='recipe-match-summary';
    reason.textContent=[...timeLabels,...reasons].slice(0,3).join(' · ');reason.hidden=!reason.textContent;
    const score=node.querySelector('.score'); detailContent.prepend(score);
    const meta=node.querySelector('.card-meta'); copy.prepend(title); title.after(meta); meta.append(node.querySelector('.details'));
    const rank = node.querySelector('.rank'); rank.classList.add('recipe-rank-badge'); rank.setAttribute('aria-label', `Result rank ${recipe.rank}`); wrapper.append(rank);
    meta.after(reason);
    const sources=document.createElement('p');sources.className='recipe-retrieval-source';
    const sourceLabels=[];
    if(recipe.source_level==='relaxed')sourceLabels.push('Relaxed recall · original eligibility still applies');
    if(recipe.bm25_source_level)sourceLabels.push('BM25 · '+recipe.bm25_source_level.replaceAll('_',' '));
    else if(recipe.bm25_rank!=null || data.mode==='bm25')sourceLabels.push('BM25');
    if(recipe.vector_matched || recipe.vector_rank!=null || data.mode==='vector')sourceLabels.push(recipe.vector_source_level==='relaxed'?'Vector · relaxed':'Vector');
    for(const label of sourceLabels){const badge=document.createElement('span');badge.textContent=label;sources.append(badge);}
    if(!sourceLabels.length)sources.textContent='Retrieval source unavailable';
    meta.after(sources);

    results.append(node);
  });
  const research=document.getElementById('retrieval-research-details');
  if(research){
    let diagnostics=document.getElementById('retrieval-result-diagnostics');
    if(!diagnostics){diagnostics=document.createElement('div');diagnostics.id='retrieval-result-diagnostics';research.append(diagnostics);}
    diagnostics.replaceChildren(...results.querySelectorAll(':scope > .active-filters,:scope > .ranking-run-details'));
  }
  results.classList.remove('hidden'); empty.classList.add('hidden');
  document.dispatchEvent(new CustomEvent('recipe-results', {detail: data.results}));
}
function escapeHtml(value) { const div = document.createElement('div'); div.textContent = value; return div.innerHTML; }

const displayValue = value => value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length) ? '—' : escapeHtml(Array.isArray(value) ? value.join(', ') : String(value));
const listItems = values => (values || []).map(value => `<li>${escapeHtml(String(value))}</li>`).join('') || '<li>Not available</li>';

function closeRecipeDetail() {
  detailRequestId++;
  detailPanel.classList.add('hidden');
  document.body.classList.remove('modal-open');
  detailTrigger?.focus();
}

let detailRequestId=0;

async function loadRecipeDetail(recipeId, trigger, snapshot=null) {
  const requestId=++detailRequestId;
  detailTrigger = trigger;
  detailPanel.classList.remove('hidden');
  document.body.classList.add('modal-open');
  detailPanel.innerHTML = '<div class="detail-card"><p class="detail-loading">Loading recipe details…</p></div>';
  try {
    let body, snapshotNotice=false;
    try {
      const response=await fetch(`/recipes/${encodeURIComponent(recipeId)}`);
      body=await response.json();
      if(!response.ok) throw new Error(typeof body.detail==='string'?body.detail:`HTTP ${response.status}`);
    } catch(error) {
      if(!snapshot || String(snapshot.recipe_id ?? snapshot.recipeid)!==String(recipeId)) throw error;
      body={...snapshot,recipeid:recipeId,source_identifier:'Saved generation snapshot',image_source:snapshot.image_source || 'snapshot'};
      snapshotNotice=true;
    }
    if(requestId!==detailRequestId) return;
    document.dispatchEvent(new CustomEvent('recipe-selection', {detail: String(body.recipeid)}));
    const nutrition = [
      ['Calories / serving', body.calories], ['Protein', body.proteincontent], ['Carbohydrates', body.carbohydratecontent],
      ['Fat', body.fatcontent], ['Fiber', body.fibercontent], ['Sugar', body.sugarcontent], ['Sodium', body.sodiumcontent],
      ['Cholesterol / serving (mg)', body.cholesterolcontent],
    ].map(([label, value]) => `<div><span>${label}</span><b>${displayValue(value)}</b></div>`).join('');
    const ingredientKey=value=>String(value).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
    const originalNames=new Set((body.ingredients||[]).map(ingredientKey));
    const extraNames=[...new Map((body.extract_ingredients||[]).filter(value=>typeof value==='string'&&ingredientKey(value)&&!originalNames.has(ingredientKey(value))).map(value=>[ingredientKey(value),value])).values()];
    detailPanel.innerHTML = `<div class="detail-card">
      <button class="detail-close" type="button" aria-label="Close recipe details">×</button>
      ${snapshotNotice?'<p class="search-warning detail-snapshot">Live recipe details are unavailable. Showing the stored recipe data from this generation; missing fields are not filled in.</p>':''}
      <div class="detail-heading"><img src="${escapeHtml(body.display_image_url || '/assets/recipe-icons/default.svg')}" alt="${escapeHtml(body.name || 'Recipe image')}" /><div><p class="eyebrow">RECIPE DETAIL · ${displayValue(body.recipeid)}</p><h2>${displayValue(body.name || 'Untitled recipe')}</h2><p>${displayValue(body.description || 'No description available.')}</p><small>${displayValue(body.source_identifier)} · ${displayValue(body.image_source)}</small></div></div>
      <div class="detail-grid"><section><h3>Recipe information</h3><dl><div><dt>Recipe ID</dt><dd>${displayValue(body.recipeid)}</dd></div><div><dt>Category</dt><dd>${displayValue(body.recipecategory)}</dd></div><div><dt>Prep time</dt><dd>${displayValue(body.prep_time_minutes)} min</dd></div><div><dt>Cook time</dt><dd>${displayValue(body.cook_time_minutes)} min</dd></div><div><dt>Total time</dt><dd>${displayValue(body.total_time_minutes)} min</dd></div><div><dt>Rating</dt><dd>${displayValue(body.aggregatedrating)}</dd></div><div><dt>Servings</dt><dd>${displayValue(body.recipeservings)}</dd></div></dl></section><section><h3>Nutrition</h3><div class="nutrition-grid">${nutrition}</div></section></div>
      <div class="detail-grid"><section><h3>Ingredients</h3><p class="field-help">Recorded ingredient names only; quantities are not included.</p><ul class="detail-list">${listItems(body.ingredients)}</ul><section class="detail-extracted-ingredients" aria-label="Additional ingredients from instructions"><h3>From instructions</h3><p class="field-help">Ingredient names mentioned in the steps, not listed above.</p>${extraNames.length?`<ul class="detail-list">${listItems(extraNames)}</ul>`:'<p class="field-help">No additional ingredient names recorded.</p>'}</section></section><section><h3>Instructions</h3><ol class="detail-list">${listItems(body.instructions)}</ol></section></div></div>`;
    RecipeImage.bind(detailPanel.querySelector('.detail-heading img'),detailPanel.querySelector('.detail-heading'),body);
    detailPanel.querySelector('.detail-close').addEventListener('click', closeRecipeDetail);
    detailPanel.querySelector('.detail-close').focus();
  } catch (error) {
    if(requestId!==detailRequestId) return;
    detailPanel.innerHTML = `<div class="detail-card"><button class="detail-close" type="button" aria-label="Close recipe details">×</button><div class="error"><strong>Could not load recipe details</strong><pre>${escapeHtml(error.message)}</pre></div></div>`;
    detailPanel.querySelector('.detail-close').addEventListener('click', closeRecipeDetail);
  }
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !detailPanel.classList.contains('hidden')) closeRecipeDetail();
});

async function refreshEsStatus() {
  const label = document.querySelector('#es-status');
  try {
    const response = await fetch('/health');
    if (!response.ok) throw new Error();
    label.textContent = 'ES online';
    label.className = 'es-status online';
  } catch {
    label.textContent = 'ES unavailable';
    label.className = 'es-status offline';
  }
}

refreshEsStatus();
window.setInterval(refreshEsStatus, 30000);

let retrievalScrollLock=null;
function releaseRetrievalScroll(lock,restore){
 if(!lock || retrievalScrollLock!==lock)return;
 for(const event of ['wheel','touchmove','keydown'])window.removeEventListener(event,lock.onNavigate);
 lock.stage.style.minHeight=lock.minimum;retrievalScrollLock=null;
 if(restore&&!lock.navigated)requestAnimationFrame(()=>{if(!retrievalScrollLock)window.scrollTo({top:lock.y,left:lock.x,behavior:'instant'});});
}
function holdRetrievalScroll(){
 if(retrievalScrollLock)releaseRetrievalScroll(retrievalScrollLock,false);
 const stage=document.getElementById('stage-retrieval');
 const lock={stage,minimum:stage.style.minHeight,y:window.scrollY,x:window.scrollX,navigated:false};
 lock.onNavigate=event=>{if(event.type!=='keydown'||['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key))lock.navigated=true;};
 for(const event of ['wheel','touchmove','keydown'])window.addEventListener(event,lock.onNavigate,{passive:true});
 stage.style.minHeight=stage.getBoundingClientRect().height+'px';retrievalScrollLock=lock;return lock;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const optionalNumber = id => { const value = document.querySelector(id).value; return value === '' ? null : Number(value); };
  const mode = document.querySelector('#mode').value;
  const body = {
    query: document.querySelector('#query').value || document.getElementById('vector-query').value, mode,
    bm25_query: document.querySelector('#query').value,
    vector_query: document.getElementById('vector-query').value,
    vector_scope_query:document.getElementById('vector-scope-query').value,
    vector_scope_weight:Number(document.getElementById('vector-scope-weight').value),
    apply_preference_rerank:document.getElementById('apply-preference-rerank').checked,
    cuisine_target:document.getElementById('cuisine-target').value,
    cuisine_role:document.getElementById('cuisine-role').value,
    meal_type_target:document.getElementById('meal-type-target').value,
    bm25_meal_type:document.getElementById('bm25-meal-type').value,
    retrieval_strategy:'text',
    scope_meal_types:[],
    scope_cuisines:[],
    category_required:split(document.getElementById('category-required').value),category_excluded:split(document.getElementById('category-excluded').value),
    dish_name_target:document.getElementById('dish-name-target').value,dish_type_target:document.getElementById('dish-type-target').value,
    bm25_available_boost:Number(document.getElementById('bm25-available-boost').value),
    preference_available:split(document.getElementById('preference-available').value),
    strict_candidate_threshold: Number(document.getElementById('bm25-fallback-threshold').value),
    relaxed_candidates:Number(document.getElementById('relaxed-candidates').value),near_miss_target:Number(document.getElementById('near-miss-target').value),core_ingredients:split(document.getElementById('core-ingredients').value),
    labels: split(document.querySelector('#labels').value),
    include_ingredients: split(document.querySelector('#include').value),
    exclude_ingredients: split(document.querySelector('#exclude').value),
    cook_time: document.querySelector('#cook-time').value || null,
    max_total_time_minutes: optionalNumber('#max-total-time'),
    max_calories: optionalNumber('#max-calories'),
    size: Number(document.querySelector('#size').value),
    bm25_dish_name: document.getElementById('bm25-dish-name').value,
    bm25_dish_type: document.getElementById('bm25-dish-type').value,
    bm25_cuisine: document.getElementById('bm25-cuisine').value,
    bm25_cuisine_boost:Number(document.getElementById('bm25-cuisine-boost').value),
    bm25_categories: split(document.getElementById('bm25-categories').value),
  };
  if(body.retrieval_strategy==='label_scope' && !body.scope_meal_types.length && !body.scope_cuisines.length) {document.getElementById('retrieval-source').textContent='Label scope requires a meal type or cuisine. Add a scope value or switch to Content search.';return;}
  try { body.required_expression=globalThis.RecipeRequired?.parse(document.getElementById('required-expression').value)||null; body.numeric_filters = globalThis.RecipeBounds?.collect() || []; }
  catch (error) { document.querySelector('#retrieval-source').textContent = error.message; return; }
  body.bm25_candidates=Number(document.getElementById('bm25-candidates').value);
  body.vector_candidates=Number(document.getElementById('vector-candidates').value);
  body.rrf_k=Number(document.getElementById('rrf-k').value);
  if (mode !== 'bm25') body.vector_num_candidates = Number(document.querySelector('#vector-num-candidates').value);
  if (mode === 'hybrid') Object.assign(body, {
    execution: document.querySelector('#execution').value,
    rrf_k: Number(document.querySelector('#rrf-k').value),
    bm25_candidates: Number(document.querySelector('#bm25-candidates').value),
    vector_candidates: Number(document.querySelector('#vector-candidates').value),
    bm25_boost: Number(document.querySelector('#bm25-boost').value),
    vector_boost: Number(document.querySelector('#vector-boost').value),
  });
  {
    for (const group of ['available','prefer','avoid','cuisine','meal_type','dish_type','healthy','quick','easy','flavor']) body['preference_weight_' + group] = Number(document.getElementById('weight-' + group).value);
    body.rating_boost = Number(document.querySelector("#rating-boost").value);
    body.preference_lambda = Number(document.querySelector('#preference-lambda').value);
    for (const group of ['available','prefer','avoid','cuisine','meal_type','dish_type','healthy','quick','easy','flavor']) body['preference_' + group] = split(document.getElementById('preference-' + group).value);
  }
  globalThis.RecipeRetrievalTabs?.prepare(body);
  const scrollLock=holdRetrievalScroll();
  const flowToken = globalThis.RecipeFlow?.startRetrieval(body);
  if (globalThis.RecipeFlow && !flowToken){releaseRetrievalScroll(scrollLock,false);return;}
  const isCurrent = () => !globalThis.RecipeFlow || globalThis.RecipeFlow.current(flowToken);
  globalThis.RecipeRetrievalTabs?.begin(body);
  setLoading(true, body.mode); results.classList.add('hidden');
  requestAnimationFrame(()=>{if(retrievalScrollLock===scrollLock&&!scrollLock.navigated)window.scrollTo({top:scrollLock.y,left:scrollLock.x,behavior:'instant'});});
  const browserStarted = performance.now();
  try {
    const response = await fetch('/api/search/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), signal: flowToken?.signal});
    if (!response.ok) {
      const rawResponse = await response.text();
      let data;
      try { data = JSON.parse(rawResponse); } catch { data = null; }
      const detail = data?.detail;
      const serverMessage = Array.isArray(detail)
        ? detail.map(issue => `${(issue.loc || []).join('.')}: ${issue.msg}`).join('\n')
        : typeof detail === 'object' && detail !== null
        ? `${detail.message || 'API request failed'}\n${detail.exception_type || 'Error'}: ${detail.exception || ''}`
        : detail || rawResponse || 'Unable to search';
      throw new Error(`HTTP ${response.status} ${response.statusText}\n${serverMessage}`);
    }
    const data = await readSearchStream(response, isCurrent);
    if (!isCurrent()) return;
    if(body.retrieval_strategy==='label_scope' && data.retrieval_strategy!=='label_scope') throw new Error('The backend did not confirm label-scope retrieval. Restart the server and retry; results were discarded.');
    if(globalThis.RecipeRetrievalTabs && data.mode!==body.mode)throw new Error('The response mode does not match this tab. Results were discarded.');
    showTimings(data, performance.now() - browserStarted);
    showResults(data, body);
    globalThis.RecipeRetrievalFlow?.complete(data);
    globalThis.RecipeFlow?.retrievalComplete(flowToken,data);
    globalThis.RecipeRetrievalTabs?.complete(data,body);
  } catch (error) {
    if (!isCurrent()) return;
    globalThis.RecipeFlow?.retrievalFailed(flowToken);
    globalThis.RecipeRetrievalTabs?.fail(body,error.message);
    globalThis.RecipeRetrievalFlow?.fail();
    progress.querySelectorAll('b').forEach(label => {
      if (['Running', 'Running…', 'Waiting'].includes(label.textContent)) label.textContent = 'Unavailable';
    });
    document.querySelector('#total-time').textContent = 'Failed';
    document.querySelector('#e2e-time').textContent = milliseconds(performance.now() - browserStarted);
    const diagnostics = [
      `${error.name || 'Error'}: ${error.message || 'Unknown error'}`,
      error.cause ? `Cause: ${error.cause}` : null,
      `Endpoint: ${window.location.origin}/api/search/stream`,
      `Request: ${JSON.stringify(body)}`,
    ].filter(Boolean).join('\n');
    results.innerHTML = `<div class="error"><strong>Search request failed</strong><pre>${escapeHtml(diagnostics)}</pre></div>`;
    const research=document.getElementById('retrieval-research-details');
  if(research){
    let diagnostics=document.getElementById('retrieval-result-diagnostics');
    if(!diagnostics){diagnostics=document.createElement('div');diagnostics.id='retrieval-result-diagnostics';research.append(diagnostics);}
    diagnostics.replaceChildren(...results.querySelectorAll(':scope > .active-filters,:scope > .ranking-run-details'));
  }
  results.classList.remove('hidden'); empty.classList.add('hidden');
  }
  finally {releaseRetrievalScroll(scrollLock,isCurrent()); if (isCurrent()) {setLoading(false); document.querySelectorAll('.dot').forEach(dot => dot.classList.remove('active'));} }
});

// Keep filled controls distinct from placeholder examples, including parsed values.
function highlightFilledFields() {
  document.querySelectorAll('.search-panel input:not([type="checkbox"]), .search-panel textarea, .search-panel select').forEach(field => {
    field.classList.toggle('has-value', Boolean(field.value.trim()));
  });
}
document.addEventListener('input', highlightFilledFields);
document.addEventListener('change', highlightFilledFields);
document.addEventListener('retrieval-fields-filled', highlightFilledFields);
highlightFilledFields();

document.getElementById('required-expression').addEventListener('input',()=>{const preview=document.getElementById('required-expression-preview');try{preview.textContent=RecipeRequired.format(RecipeRequired.parse(document.getElementById('required-expression').value))||'Any included ingredient (legacy OR)';}catch(error){preview.textContent=error.message;}});

function describeFinalCuisine(){
 const name=document.getElementById('dish-name-target').value.trim(),type=document.getElementById('dish-type-target').value.trim();
 const cuisine=document.getElementById('cuisine-target').value.trim(),required=document.getElementById('cuisine-role').value==='required';
 document.getElementById('final-cuisine-status').textContent=!cuisine?'No cuisine target specified.':name?`Dish name is present (${name}); cuisine only affects ranking and explanations, even when parsed as Required.`:type?`Dish type is present (${type}); cuisine only affects ranking and explanations, even when parsed as Required.`:required?`No dish name or dish type: Generate must confirm ${cuisine}. Unknown cuisine will not be recommended.`:'Cuisine is a preference; it only affects ranking and explanations.';
}

for(const id of ['dish-name-target','dish-type-target','cuisine-target','cuisine-role'])document.getElementById(id).addEventListener('input',describeFinalCuisine);
document.addEventListener('retrieval-fields-filled',describeFinalCuisine);
describeFinalCuisine();

// Tabs reuse the existing safe renderer and detail handlers; no copied innerHTML.
globalThis.RecipeRetrievalView={
 updateSettings:updateRetrievalSettings,
 render(data,body){showResults(data,body);showTimings(data,0);globalThis.RecipeRetrievalFlow?.start(body.mode,{execution:body.execution,include:body.include_ingredients||[],exclude:body.exclude_ingredients||[],expression:body.required_expression,strategy:body.retrieval_strategy});globalThis.RecipeRetrievalFlow?.complete(data);},
 clear(){document.getElementById('retrieval-result-diagnostics')?.replaceChildren();results.replaceChildren();results.classList.add('hidden');progress.classList.add('hidden');globalThis.RecipeRetrievalFlow?.clear();},
 cancel(){releaseRetrievalScroll(retrievalScrollLock,false);globalThis.RecipeFlow?.cancelRetrieval();setLoading(false,document.getElementById('mode').value);},
 action(){setLoading(false,document.getElementById('mode').value);}
};
