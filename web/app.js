const form = document.querySelector('#search-form');
const button = document.querySelector('#submit-button');
const progress = document.querySelector('#progress');
const results = document.querySelector('#results');
const empty = document.querySelector('#empty');
const detailPanel = document.querySelector('#detail-panel');
const template = document.querySelector('#card-template');
const split = value => value.split(',').map(item => item.trim()).filter(Boolean);
let detailTrigger = null;

function setLoading(loading, needsEmbedding = true) {
  button.disabled = loading;
  button.innerHTML = loading ? 'Searching…' : 'Search <span>→</span>';
  // Keep completed measurements visible next to the results.
  if (loading) progress.classList.remove('hidden');
  if (loading) {
    document.querySelector('#embedding-time').textContent = needsEmbedding ? 'Pending' : 'Skipped (BM25)';
    document.querySelector('#retrieval-time').textContent = 'Waiting';
    document.querySelector('#total-time').textContent = 'Running';
    document.querySelectorAll('.dot')[0].classList.remove('active');
    document.querySelectorAll('.dot')[1].classList.remove('active');
  }
}

function updateProgress(event) {
  const isEmbedding = event.step === 'embedding';
  const time = document.querySelector(isEmbedding ? '#embedding-time' : '#retrieval-time');
  const dot = document.querySelectorAll('.dot')[isEmbedding ? 0 : 1];
  if (event.status === 'running') { time.textContent = 'Loading…'; dot.classList.add('active'); }
  if (event.status === 'complete') { time.textContent = `${event.elapsed_ms} ms`; dot.classList.remove('active'); }
  if (event.status === 'skipped') { time.textContent = 'Skipped (BM25)'; dot.classList.remove('active'); }
}

async function readSearchStream(response) {
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
      if (event.type === 'progress') updateProgress(event);
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
    ...(request.include_ingredients || []).map(item => `Include: ${item}`),
    ...(request.exclude_ingredients || []).map(item => `Exclude: ${item}`),
    request.cook_time ? labels[request.cook_time] : null,
    request.max_total_time_minutes !== null && request.max_total_time_minutes !== undefined
      ? `Max total: ${request.max_total_time_minutes} min` : null,
    request.max_calories !== null && request.max_calories !== undefined
      ? `Max calories: ${request.max_calories} / serving` : null,
  ].filter(Boolean);
  if (!chips.length) return '';
  return `<div class="active-filters" aria-label="Active filters"><span>Active filters</span>${chips.map(chip => `<span class="filter-chip">${escapeHtml(chip)}</span>`).join('')}</div>`;
}

function renderHighlight(value) {
  return escapeHtml(value).replaceAll('&lt;em&gt;', '<mark>').replaceAll('&lt;/em&gt;', '</mark>');
}

function lexicalEvidence(recipe) {
  const fieldLabels = {name: 'Title', keywords: 'Tags', ingredients: 'Ingredients', description: 'Description'};
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
  const embedding = data.mode === 'bm25' ? 'embedding skipped' : `embedding ${data.timings.query_embedding_ms} ms`;
  const totalPrefix = data.match_result_size?.relation === 'gte' ? '≥' : '';
  const matched = `${totalPrefix}${data.match_result_size?.value ?? data.result_count}`;
  const resultSummary = data.mode === 'vector'
    ? `Vector candidates returned: ${data.result_count}`
    : `Match result size: ${matched}`;
  results.innerHTML = `${activeFilterChips(request)}<p class="result-summary"><strong>${resultSummary}</strong> · showing ${data.result_count} · ${data.mode.toUpperCase()} · ${embedding} · ES ${data.timings.es_retrieving_ms} ms · total ${data.timings.total_ms} ms</p>`;
  if (!data.results.length) results.innerHTML += '<p class="empty">No recipes matched these filters. Try broadening your ingredients.</p>';
  data.results.forEach(recipe => {
    const node = template.content.cloneNode(true);
    const image = node.querySelector('img'); const wrapper = node.querySelector('.recipe-image');
    const url = recipe.display_image_url;
    const placeholder = recipe.fallback_image_url || '/assets/recipe-placeholder.svg';
    image.src = url || placeholder;
    image.alt = recipe.name || 'Recipe image';
    image.title = recipe.image_source || 'display image';
    wrapper.classList.add('has-image');
    image.onerror = () => { image.onerror = null; image.src = placeholder; };
    node.querySelector('.rank').textContent = `#${recipe.rank}`;
    node.querySelector('.score').textContent = data.mode === 'vector'
      ? `semantic similarity ${Number(recipe.semantic_similarity).toFixed(4)}`
      : `${data.mode === 'hybrid' ? 'hybrid' : 'BM25'} score ${recipe.score}`;
    const title = node.querySelector('.recipe-title');
    const titleHighlight = recipe.match_highlights?.name?.[0];
    title.innerHTML = titleHighlight ? renderHighlight(titleHighlight) : escapeHtml(recipe.name || 'Untitled recipe');
    title.addEventListener('click', () => loadRecipeDetail(recipe.recipeid, title));
    node.querySelector('.description').textContent = recipe.description || 'No description available.';
    node.querySelector('.why-matched').innerHTML = data.mode === 'vector' ? vectorEvidence(recipe) : lexicalEvidence(recipe);
    const tags = [recipe.recipecategory, ...(recipe.keywords || []).slice(0, 3)].filter(Boolean);
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
    results.append(node);
  });
  results.classList.remove('hidden'); empty.classList.add('hidden');
}
function escapeHtml(value) { const div = document.createElement('div'); div.textContent = value; return div.innerHTML; }

const displayValue = value => value === null || value === undefined || value === '' ? '—' : escapeHtml(String(value));
const listItems = values => (values || []).map(value => `<li>${escapeHtml(String(value))}</li>`).join('') || '<li>Not available</li>';

function closeRecipeDetail() {
  detailPanel.classList.add('hidden');
  document.body.classList.remove('modal-open');
  detailTrigger?.focus();
}

async function loadRecipeDetail(recipeId, trigger) {
  detailTrigger = trigger;
  detailPanel.classList.remove('hidden');
  document.body.classList.add('modal-open');
  detailPanel.innerHTML = '<div class="detail-card"><p class="detail-loading">Loading recipe details…</p></div>';
  try {
    const response = await fetch(`/recipes/${encodeURIComponent(recipeId)}`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    const nutrition = [
      ['Calories / serving', body.calories], ['Protein', body.proteincontent], ['Carbohydrates', body.carbohydratecontent],
      ['Fat', body.fatcontent], ['Fiber', body.fibercontent], ['Sugar', body.sugarcontent], ['Sodium', body.sodiumcontent],
    ].map(([label, value]) => `<div><span>${label}</span><b>${displayValue(value)}</b></div>`).join('');
    detailPanel.innerHTML = `<div class="detail-card">
      <button class="detail-close" type="button" aria-label="Close recipe details">×</button>
      <div class="detail-heading"><img src="${escapeHtml(body.display_image_url || '/assets/recipe-placeholder.svg')}" alt="${escapeHtml(body.name || 'Recipe image')}" /><div><p class="eyebrow">RECIPE DETAIL · ${displayValue(body.recipeid)}</p><h2>${displayValue(body.name || 'Untitled recipe')}</h2><p>${displayValue(body.description || 'No description available.')}</p><small>${displayValue(body.source_identifier)} · ${displayValue(body.image_source)}</small></div></div>
      <div class="detail-grid"><section><h3>Recipe information</h3><dl><div><dt>Recipe ID</dt><dd>${displayValue(body.recipeid)}</dd></div><div><dt>Category</dt><dd>${displayValue(body.recipecategory)}</dd></div><div><dt>Prep time</dt><dd>${displayValue(body.prep_time_minutes)} min</dd></div><div><dt>Cook time</dt><dd>${displayValue(body.cook_time_minutes)} min</dd></div><div><dt>Total time</dt><dd>${displayValue(body.total_time_minutes)} min</dd></div><div><dt>Rating</dt><dd>${displayValue(body.aggregatedrating)}</dd></div><div><dt>Servings</dt><dd>${displayValue(body.recipeservings)}</dd></div></dl></section><section><h3>Nutrition</h3><div class="nutrition-grid">${nutrition}</div></section></div>
      <div class="detail-grid"><section><h3>Ingredients</h3><ul class="detail-list">${listItems(body.ingredients)}</ul></section><section><h3>Instructions</h3><ol class="detail-list">${listItems(body.instructions)}</ol></section></div></div>`;
    const detailImage = detailPanel.querySelector('.detail-heading img');
    const detailFallbackImage = body.fallback_image_url || '/assets/recipe-placeholder.svg';
    detailImage.addEventListener('error', () => {
      detailImage.onerror = null;
      detailImage.src = detailFallbackImage;
      detailImage.title = 'Fallback display image';
    }, { once: true });
    detailPanel.querySelector('.detail-close').addEventListener('click', closeRecipeDetail);
    detailPanel.querySelector('.detail-close').focus();
  } catch (error) {
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

form.addEventListener('submit', async event => {
  event.preventDefault();
  const optionalNumber = id => { const value = document.querySelector(id).value; return value === '' ? null : Number(value); };
  const body = { query: document.querySelector('#query').value, mode: document.querySelector('#mode').value, include_ingredients: split(document.querySelector('#include').value), exclude_ingredients: split(document.querySelector('#exclude').value), cook_time: document.querySelector('#cook-time').value || null, max_total_time_minutes: optionalNumber('#max-total-time'), max_calories: optionalNumber('#max-calories'), size: Number(document.querySelector('#size').value) || 10 };
  setLoading(true, body.mode !== 'bm25'); results.classList.add('hidden');
  try {
    const response = await fetch('/api/search/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!response.ok) {
      const rawResponse = await response.text();
      let data;
      try { data = JSON.parse(rawResponse); } catch { data = null; }
      const detail = data?.detail;
      const serverMessage = typeof detail === 'object'
        ? `${detail.message || 'API request failed'}\n${detail.exception_type || 'Error'}: ${detail.exception || ''}`
        : detail || rawResponse || 'Unable to search';
      throw new Error(`HTTP ${response.status} ${response.statusText}\n${serverMessage}`);
    }
    const data = await readSearchStream(response);
    document.querySelector('#total-time').textContent = `${data.timings.total_ms} ms`;
    showResults(data, body);
  } catch (error) {
    const diagnostics = [
      `${error.name || 'Error'}: ${error.message || 'Unknown error'}`,
      error.cause ? `Cause: ${error.cause}` : null,
      `Endpoint: ${window.location.origin}/api/search`,
      `Request: ${JSON.stringify(body)}`,
    ].filter(Boolean).join('\n');
    results.innerHTML = `<div class="error"><strong>Search request failed</strong><pre>${escapeHtml(diagnostics)}</pre></div>`;
    results.classList.remove('hidden'); empty.classList.add('hidden');
  }
  finally { setLoading(false); document.querySelectorAll('.dot').forEach(dot => dot.classList.remove('active')); }
});
