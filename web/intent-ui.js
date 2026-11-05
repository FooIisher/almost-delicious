/* Intent analysis is a preview, independent of retrieval and manual filters. */
(() => {
  const model = document.querySelector('#intent-model');
  const query = document.querySelector('#user-query');
  const analyze = document.querySelector('#analyze-intent');
  const panel = document.querySelector('#intent-panel');
  const state = document.querySelector('#intent-state');
  const message = document.querySelector('#intent-message');
  const content = document.querySelector('#intent-content');
  const download = document.querySelector('#download-intent');
  const labels = {
    recipe_search: 'Recipe search', meal_planning: 'Meal planning', recipe_comparison: 'Recipe comparison',
    recipe_how_to: 'Cooking instructions', recipe_question_answering: 'Recipe Q&A',
    unsupported_request: 'Outside recipe scope', unknown: 'Unknown intent',
    name_search: 'Name search', constraint_search: 'Constraint search',
  };
  const humanize = value => labels[value] || String(value || '').replaceAll('_', ' ');
  const esc = value => { const element = document.createElement('span'); element.textContent = String(value ?? ''); return element.innerHTML; };
  const tags = values => values.map(value => `<span class="intent-chip">${esc(humanize(value))}</span>`).join('');
  let controller = null;
  let revision = 0;
  let lastResult = null;
  let lastSignature = null;
  let pendingSignature = null;

  function invalidate() {
    if (!lastResult && !controller) return;
    document.querySelector('#retrieval-source').textContent = 'Input or model changed. Retrieval fields retain their previous values; analyze again to replace them.';
    revision += 1;
    controller?.abort();
    controller = null;
    lastResult = null;
    lastSignature = null;
    pendingSignature = null;
    content.hidden = true;
    content.replaceChildren();
    download.disabled = true;
    analyze.disabled = false;
    analyze.textContent = 'Analyze intent';
    panel.removeAttribute('aria-busy');
    state.textContent = 'Query changed';
    state.className = 'intent-badge pending';
    message.textContent = 'The input changed. Analyze again to see its interpretation.';
  }

  function render(data) {
    const parsed = data.parsed;
    const isJev = data.model === 'typesafe-ai/jev';
    const statusLabels = {ready: 'Parsed', needs_clarification: 'Needs clarification', unsupported: 'Outside scope'};
    state.textContent = statusLabels[parsed.status];
    state.className = `intent-badge ${parsed.status === 'ready' ? 'ready' : 'pending'}`;
    message.textContent = 'Interpretation complete. Review the recognized information below.';
    const supported = data.execution_support === 'supported';
    const alerts = [];
    for (const warning of data.warnings || (isJev ? ['Jev evaluates dictionary/regex candidates. Ingredient coverage is limited; empty fields do not confirm absence of constraints.'] : [])) alerts.push(`<div class="intent-notice pending">${esc(warning)}</div>`);
    if (parsed.clarification_question) alerts.push(`<div class="intent-notice pending"><strong>Clarification needed</strong><p>${esc(parsed.clarification_question)}</p>${tags(parsed.clarification_reasons)}</div>`);
    if (!supported) alerts.push(`<div class="intent-notice"><strong>${parsed.intent === 'unknown' ? 'No reliable intent yet' : 'This task is not executable in this prototype'}</strong><p>${parsed.intent === 'unknown' ? 'Provide a more specific recipe request.' : 'The parser can recognize this request; the current application executes recipe retrieval only.'}</p>${parsed.unsupported_reason ? `<p>${esc(humanize(parsed.unsupported_reason))}</p>` : ''}</div>`);
    if (data.constraint_rows.some(row => row.source === 'system_default')) alerts.push('<div class="intent-notice pending"><strong>System default needs confirmation</strong><p>The existing schema interprets “quick” as at most 30 minutes. This is a suggested default, not an explicit user limit or an applied filter.</p></div>');

    const rows = data.constraint_rows.map(row => {
      const values = Array.isArray(row.value) ? tags(row.value) : `<strong>${esc(row.operator)} ${esc(humanize(row.value))}</strong> <span>${esc(row.unit)}</span>`;
      const status = row.needs_confirmation ? 'Suggested default · confirm'
        : row.support === 'supported' ? 'Recognized · not applied'
        : row.support === 'unsupported' ? 'No matching filter'
        : row.support === 'preference' ? 'Preference · not a hard filter' : 'Context only';
      return `<div class="intent-constraint ${row.needs_confirmation ? 'suggested' : ''}"><div><span class="intent-field-label">${esc(row.label)}</span><div class="intent-values">${values}</div>${row.evidence ? `<p>Source: ${esc(row.evidence)}</p>` : ''}</div><span class="intent-badge ${row.support === 'unsupported' || row.needs_confirmation ? 'pending' : ''}">${status}</span></div>`;
    }).join('');

    const intentScores = Object.entries(data.intent_scores).sort((a, b) => b[1] - a[1]).map(([intent, probability]) => {
      const percent = (probability * 100).toFixed(1);
      return `<div class="intent-score ${intent === parsed.intent ? 'selected' : ''}"><span>${esc(humanize(intent))}</span><meter min="0" max="1" value="${probability}" aria-label="${esc(humanize(intent))} probability">${percent}%</meter><b>${percent}%</b></div>`;
    }).join('');
    const targetSections = [];
    for (const [field, label] of [['dish_name', 'Dish name'], ['dish_type', 'Dish type'], ['meal_type', 'Meal type'], ['cuisine', 'Cuisine']]) {
      const value = parsed[field] ?? parsed.extraction?.[field];
      const evidence = parsed.target_evidence?.[field] ?? parsed.extraction?.target_evidence?.[field];
      targetSections.push(`<div><h4>${label}</h4>${value ? tags([value]) : `<p>${isJev ? 'Not supported by this adapter' : 'Not identified'}</p>`}${evidence ? `<p>Source: ${esc(evidence)}</p>` : ''}</div>`);
    }
    if (data.corrections?.length) targetSections.push(`<div><h4>Spelling corrections</h4>${tags(data.corrections.map(x => `${x.original} → ${x.normalized}`))}</div>`);
    if (parsed.recipe_names.length) targetSections.push(`<div><h4>Named recipes</h4>${tags(parsed.recipe_names)}</div>`);
    if (parsed.recipe_references.length) targetSections.push(`<div><h4>Resolved recipes</h4>${tags(parsed.recipe_references.map(id => {
      const recipe = data.context.recipes.find(item => item.id === id);
      return recipe ? `${recipe.name} · ${id}` : id;
    }))}</div>`);
    if (parsed.comparison_dimensions.length) targetSections.push(`<div><h4>Comparison criteria</h4>${tags(parsed.comparison_dimensions)}</div>`);
    if (parsed.question_type) targetSections.push(`<div><h4>Question type</h4>${tags([parsed.question_type])}</div>`);
    if (parsed.missing_fields.length) targetSections.push(`<div><h4>Missing information</h4>${tags(parsed.missing_fields)}</div>`);
    if (parsed.uncertain_questions.length) targetSections.push(`<div><h4>Uncertain decisions</h4>${tags(parsed.uncertain_questions)}</div>`);

    content.innerHTML = `
      <blockquote class="intent-query">${esc(data.raw_query)}</blockquote>
      <div class="intent-overview">
        <div><span class="intent-field-label">Primary intent</span><h3>${esc(humanize(parsed.intent))}</h3><p>${esc(parsed.search_type ? humanize(parsed.search_type) : 'Task classification')}</p></div>
        <div><span class="intent-field-label">Search description</span><h3>${esc(parsed.search_text || (isJev ? data.raw_query : '—'))}</h3><p>${isJev ? 'Original query · Jev does not generate search text' : `Schema validated · ${data.provider === 'deepseek_direct' ? 'DeepSeek direct' : 'OpenAI direct'}`}</p></div>
        <div><span class="intent-field-label">Retrieval content</span><h3>${esc(parsed.retrieval_content ?? '—')}</h3><p>Derived by application · ${esc(parsed.retrieval_content_source || 'Not applicable')}</p></div>
        <div><span class="intent-field-label">Parsing time</span><strong class="intent-metric">${(data.intent_parse_ms / 1000).toFixed(2)}<small>s</small></strong><p>Model call + preparation + validation</p></div>
      </div>
      ${alerts.join('')}
      <div class="intent-section-heading"><h4>Recognized information</h4><span>${data.constraint_rows.length} fields</span></div>
      <div class="intent-constraints">${rows || '<p class="intent-empty">No structured constraints recognized. Empty fields do not prove that the query contains no constraints.</p>'}</div>
      ${targetSections.length ? `<div class="intent-targets">${targetSections.join('')}</div>` : ''}
      <details class="intent-diagnostics"><summary>Model & diagnostics</summary><div class="intent-scores">${intentScores}</div><p>${isJev ? 'Jev reports classification probabilities; these are not measured accuracy.' : 'OpenAI models return structured information, not calibrated intent probabilities.'} Schema validation does not guarantee semantic accuracy.</p><dl><div><dt>Model</dt><dd>${esc(data.model)}</dd></div><div><dt>Prompt version</dt><dd>${esc(data.prompt_version)}</dd></div><div><dt>Schema</dt><dd>${esc(data.schema_version)}</dd></div><div><dt>Context at submission</dt><dd>${data.context.recipes.length} recipes${data.context.selected_recipe_id ? ` · selected ${esc(data.context.selected_recipe_id)}` : ''}</dd></div><div><dt>Request ID</dt><dd>${esc(data.request_id)}</dd></div></dl><p>Available ingredients do not automatically mean required ingredients. Nutritional limits retain their original evidence; serving basis must be checked before filtering.</p><details><summary>Validated JSON & raw model answers</summary><pre class="intent-json"></pre></details></details>`;
    content.querySelector('.intent-json').textContent = JSON.stringify(data, null, 2);
    content.hidden = false;
    download.disabled = false;
  }

  function renderInvalid(data) {
    state.textContent = 'Validation failed';
    state.className = 'intent-badge pending';
    message.textContent = data.message;
    const format = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    const output = data.model_output;
    const fields = output && typeof output === 'object' && !Array.isArray(output)
      ? Object.entries(output).map(([field, value]) => `<div class="intent-constraint"><div><span class="intent-field-label">${esc(humanize(field))}</span><pre>${esc(format(value))}</pre></div><span class="intent-badge pending">Unvalidated</span></div>`).join('') : '';
    const errors = (data.validation_errors || []).map(issue => `<div class="intent-notice pending"><strong>${esc(issue.field)}</strong><p>${esc(issue.reason)}</p><pre>Returned value: ${esc(format(issue.value))}</pre></div>`).join('');
    content.innerHTML = `
      <blockquote class="intent-query">${esc(data.raw_query)}</blockquote>
      <div class="intent-notice pending"><strong>Review only · retrieval blocked for this interpretation</strong><p>These are the original model values, not validated conditions. Correct the query or retry analysis.</p></div>
      <p>Model: ${esc(data.model)} · Parsing time: ${esc((data.intent_parse_ms / 1000).toFixed(2))} s</p>
      <h4>Validation errors (${(data.validation_errors || []).length})</h4>${errors}
      <h4>Model returned values · unvalidated</h4><div class="intent-constraints">${fields}</div>
      <details class="intent-diagnostics" open><summary>Raw model output</summary><pre class="intent-json"></pre></details>
      <p>Diagnostic ID: ${esc(data.diagnostic_id)} · ${data.diagnostic_saved ? 'Saved locally' : 'Could not save locally'}</p>`;
    content.querySelector('.intent-json').textContent = format(output) ?? 'No model output available';
    content.hidden = false;
    download.disabled = false;
  }

  function deriveRetrievalContent(data) {
    const parsed = data.parsed;
    const extraction = parsed.extraction;
    if (parsed.intent !== 'recipe_search') {
      parsed.retrieval_content = null;
      parsed.retrieval_content_source = 'Not applicable';
      return;
    }
    const dishName = (parsed.dish_name ?? extraction?.dish_name ?? '').trim();
    const dishType = (parsed.dish_type ?? extraction?.dish_type ?? '').trim();
    const required = extraction
      ? extraction.ingredients.filter(item => item.role === 'required').map(item => item.name)
      : (data.constraint_rows || []).filter(row => ['ingredient_required', 'ingredients_required'].includes(row.field)).flatMap(row => Array.isArray(row.value) ? row.value : [row.value]);
    const unique = [...new Map(required.filter(x => typeof x === 'string' && x.trim()).map(x => [x.trim().toLowerCase(), x.trim()])).values()];
    const searchText = (parsed.search_text || '').trim();
    parsed.retrieval_content = dishName || (dishType ? [...unique.filter(x => x.toLowerCase() !== dishType.toLowerCase()), dishType].join(' ') : searchText || data.raw_query);
    parsed.retrieval_content_source = dishName ? 'Dish name' : dishType ? (unique.length ? 'Required ingredients + Dish type' : 'Dish type') : searchText ? 'Search description' : 'Original request';
  }

  function fillRetrieval(data) {
    const parsed = data.parsed;
    const note = document.querySelector('#retrieval-source');
    if (parsed.intent !== 'recipe_search' || parsed.status !== 'ready') {
      note.textContent = 'Retrieval fields were not replaced: this interpretation needs clarification or is not recipe search.';
      return;
    }
    const extraction = parsed.extraction;
    const ingredients = role => extraction
      ? extraction.ingredients.filter(item => item.role === role).map(item => item.name)
      : (data.constraint_rows || []).filter(row => row.field === 'ingredient_' + role || row.field === 'ingredients_' + role).flatMap(row => Array.isArray(row.value) ? row.value : [row.value]);
    const soft = (extraction?.soft_preferences || (data.constraint_rows || []).filter(r => r.field === 'preferences').flatMap(r => r.value || [])).join(' ').toLowerCase();
    const values = {'preference-healthy': /\bhealthy\b/.test(soft) ? 'healthy' : '', 'preference-quick': /\b(quick|fast)\b/.test(soft) ? 'quick' : '', 'preference-easy': /\beasy\b/.test(soft) ? 'easy' : '', query: parsed.retrieval_content, include: ingredients('required').join(', '), exclude: ingredients('excluded').join(', '), 'preference-cuisine': parsed.cuisine ?? extraction?.cuisine ?? '', 'preference-meal_type': parsed.meal_type ?? extraction?.meal_type ?? '', 'preference-dish_type': parsed.dish_type ?? extraction?.dish_type ?? '', 'preference-available': ingredients('available').join(', '), 'preference-prefer': ingredients('prefer').join(', '), 'preference-avoid': ingredients('avoid').join(', ')};
    for (const [id, value] of Object.entries(values)) document.getElementById(id).value = value;
    document.dispatchEvent(new Event('retrieval-fields-filled'));
    note.textContent = `Query filled from Retrieval content (${parsed.retrieval_content_source}). Filled required/excluded ingredients and ranking preferences. Hard Labels remain manual. All retrieval fields are editable.`;
  }
  for (const id of ['query', 'include', 'exclude', 'labels']) {
    document.getElementById(id).addEventListener('input', () => {
      document.querySelector('#retrieval-source').textContent = 'Retrieval fields manually edited. Retrieval uses the current values below.';
    });
  }

  async function parse(force = false) {
    if (!query.value.trim()) {
      query.setCustomValidity('Enter a recipe request to analyze.');
      query.reportValidity();
      query.setCustomValidity('');
      query.focus();
      return;
    }
    const selectedModel = model.value;
    const body = {query: query.value, model: selectedModel};
    const signature = JSON.stringify(body);
    if (!force && (signature === lastSignature || signature === pendingSignature)) { panel.open = true; return; }
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    const requestRevision = ++revision;
    pendingSignature = signature;
    lastResult = null;
    lastSignature = null;
    download.disabled = true;
    panel.open = true;
    panel.setAttribute('aria-busy', 'true');
    analyze.disabled = true;
    analyze.textContent = 'Analyzing…';
    state.textContent = 'Analyzing';
    state.className = 'intent-badge pending';
    message.textContent = selectedModel === 'jev' ? 'Jev is classifying candidate ingredients and constraints via AI Gateway…' : `${model.selectedOptions[0].textContent} is extracting intent, ingredients and constraints…`;
    content.hidden = true;
    content.replaceChildren();
    const deadline = setTimeout(() => requestController.abort(), 40000);
    try {
      const response = await fetch(selectedModel === 'jev' ? '/intent/parse' : `/intent/parse/${selectedModel}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query: body.query}), signal: requestController.signal});
      const data = await response.json();
      if (requestRevision !== revision) return;
      if (!response.ok) {
        const detail = data.detail;
        if (detail?.code === 'invalid_model_output' && detail.validation_errors) {
          lastResult = detail;
          renderInvalid(detail);
          return;
        }
        if (detail?.diagnostic_id) {
          throw new Error(`${detail.message} Stage: ${detail.validation_stage}. Diagnostic ID: ${detail.diagnostic_id}. ${detail.diagnostic_saved ? 'Diagnostic saved locally.' : 'Diagnostic could not be saved.'}`);
        }
        throw new Error(Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : detail?.message || 'Intent parsing is unavailable. Please retry.');
      }
      if (requestRevision !== revision) return;
      lastResult = data;
      lastSignature = signature;
      deriveRetrievalContent(data);
      render(data);
      fillRetrieval(data);
    } catch (error) {
      if (requestRevision !== revision) return;
      state.textContent = 'Analysis failed';
      state.className = 'intent-badge pending';
      message.textContent = error.name === 'AbortError' ? 'Intent parsing timed out. Retry using Analyze intent.' : `${error.message} You can retry using Analyze intent.`;
    } finally {
      clearTimeout(deadline);
      if (requestRevision === revision) {
        controller = null;
        pendingSignature = null;
        analyze.disabled = false;
        analyze.textContent = 'Analyze intent';
        panel.removeAttribute('aria-busy');
      }
    }
  }

  function updateModel() {
    invalidate();
    document.querySelector('#intent-model-label').textContent = model.selectedOptions[0].textContent;
  }
  model.addEventListener('change', updateModel);
  updateModel();
  analyze.addEventListener('click', () => parse(true));
  query.addEventListener('input', invalidate);
  download.addEventListener('click', () => {
    if (!lastResult) return;
    const blob = new Blob([JSON.stringify(lastResult, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `intent-${lastResult.request_id}.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
