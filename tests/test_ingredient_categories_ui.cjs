const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() { this.style={}; this.getBoundingClientRect=()=>({height:100}); this.value = ''; this.listeners = {}; this.textContent = ''; this.selectedOptions = [{textContent: 'GPT mini'}]; this.classList = {add(){}, remove(){}, toggle(){}}; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute() {}
  removeAttribute() {}
  replaceChildren() { this.innerHTML = ''; }
  querySelector() { return new Element(); }
  querySelectorAll() { return []; }
}
const elements = new Map();
const getElement = identifier => {
  if (!elements.has(identifier)) elements.set(identifier, new Element());
  return elements.get(identifier);
};
const document = {
  querySelector: selector => getElement(selector.slice(1)),
  getElementById: getElement,
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: () => {
    const element = new Element();
    Object.defineProperty(element, 'innerHTML', {get() { return this.textContent; }});
    return element;
  },
  dispatchEvent() {},
};
let nextResponse;
const context = {document, AbortController, Event, setTimeout, clearTimeout,
  fetch: async () => ({ok: true, json: async () => structuredClone(nextResponse)})};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/intent-ui.js'), 'utf8'), context);

function ingredient(name, entity_type, role) { return {name, entity_type, role, evidence: name}; }
function response(ingredients, overrides={}) {
  const extraction = {ingredients, soft_preferences: []};
  return {model: 'gpt-4.1-mini', provider: 'openai_direct', raw_query: 'test soup', intent_parse_ms: 1,
    context: {recipes: []}, intent_scores: {}, execution_support: 'supported',
    parsed: {intent:'recipe_search', status:'ready', dish_type:'soup', dish_name:null, search_text:'soup',
      recipe_names:[], recipe_references:[], comparison_dimensions:[], missing_fields:[], uncertain_questions:[],
      extraction, ...overrides},
    constraint_rows: ingredients.map(item => ({field:'ingredient_'+item.role, label:'Ingredient', value:[item.name],
      entity_type:item.entity_type, role:item.role, evidence:item.evidence,
      support:item.entity_type==='category'?'unsupported':'supported'}))};
}
async function analyze(data) {
  const generated=require('node:child_process').spawnSync('python',['-c','import json,sys; from query_builder import build_queries; p=json.load(sys.stdin); print(json.dumps(build_queries(p)))'],{cwd:path.join(__dirname,'..'),input:JSON.stringify(data.parsed),encoding:'utf8'});
  if(generated.status!==0)throw new Error(generated.stderr);
  data.parsed.retrieval_queries=JSON.parse(generated.stdout);
  nextResponse = data;
  getElement('user-query').value = data.raw_query;
  getElement('intent-model').value = 'gpt41-mini';
  await getElement('analyze-intent').listeners.click();
}
(async () => {
  await analyze(response([ingredient('dairy','category','excluded')], {dish_type:null, search_text:'high-protein Italian lunch with canned salmon and pasta, no dairy or heavy cream'}));
  assert.equal(getElement('query').value, 'high-protein Italian lunch with canned salmon and pasta');
  await analyze(response([ingredient('onion','specific','excluded')], {dish_type:null, search_text:'soup without onion with beef'}));
  assert.equal(getElement('query').value, 'soup with beef');

  await analyze(response([ingredient('beef','specific','required'), ingredient('vegetable','category','excluded')]));
  assert.equal(getElement('include').value,'beef');
  assert.equal(getElement('exclude').value,'');
  assert.equal(getElement('query').value,'beef soup');
  assert.match(getElement('intent-content').innerHTML,/Category · Not applied to filtering or ranking/);
  await analyze(response([ingredient('onion','specific','excluded'), ingredient('meat','category','excluded')]));
  assert.equal(getElement('exclude').value,'onion');
  assert.equal(getElement('include').value,'');
  await analyze(response([ingredient('vegetable','category','available'), ingredient('beef','specific','available'),
    ingredient('meat','category','prefer'), ingredient('seafood','category','avoid')]));
  assert.equal(getElement('preference-available').value,'beef');
  assert.equal(getElement('bm25-categories').value,'vegetable, meat');
  assert.equal(getElement('preference-prefer').value,'');
  assert.equal(getElement('preference-avoid').value,'');
  assert.equal(getElement('exclude').value,'');
  await analyze(response([ingredient('vegetable','category','required')], {dish_name:'vegetable soup'}));
  assert.equal(getElement('query').value,'vegetable soup');
  assert.equal(getElement('include').value,'');
  getElement('include').value='carrot';
  getElement('include').listeners.input();
  assert.equal(getElement('include').value,'carrot');
  await analyze(response([ingredient('canned salmon','specific','available'),ingredient('pasta','specific','available')],{dish_name:null,dish_type:null,meal_type:'lunch',cuisine:'italian',search_text:'high protein Italian lunch with salmon and pasta'}));
  assert.equal(getElement('retrieval-strategy').value,'text');
  assert.equal(getElement('scope-meal-types').value,'');
  assert.equal(getElement('scope-cuisines').value,'');
  assert.equal(getElement('query').value,'high protein Italian lunch with salmon and pasta');
  assert.equal(getElement('include').value,'');
  assert.equal(getElement('preference-available').value,'canned salmon, pasta');
  await analyze(response([ingredient('beef','specific','required'), ingredient('vegetable','category','required'),
    ingredient('onion','specific','excluded'), ingredient('meat','category','excluded'), ingredient('seafood','category','prefer')]));
  assert.equal(getElement('retrieval-strategy').value,'text');
  assert.equal(getElement('scope-meal-types').value,'');
  assert.equal(getElement('scope-cuisines').value,'');
  getElement('mode').value='hybrid';
  getElement('size').value='20';
  getElement('bm25-candidates').value='50';
  getElement('vector-candidates').value='50';
  getElement('rrf-k').value='10';
  getElement('bm25-boost').value='1';
  getElement('vector-boost').value='2';
  let searchRequest;
  context.RecipeBounds={collect:()=>[{field:'total_time',operator:'lt',value:30,basis:'not_applicable'},
    {field:'calories',operator:'lt',value:500,basis:'per_serving'}]};
  context.requestAnimationFrame=fn=>fn();context.window={addEventListener(){},removeEventListener(){},scrollTo(){},setInterval(){},location:{origin:'http://localhost:8002'}};
  context.performance=performance;
  context.fetch=async (url, options) => {
    if (url==='/health') return {ok:true};
    searchRequest=JSON.parse(options.body);
    throw new Error('Captured request; no network used');
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8'),context);
  await getElement('search-form').listeners.submit({preventDefault(){}});
  assert.deepEqual(searchRequest.include_ingredients,['beef']);
  assert.deepEqual(searchRequest.exclude_ingredients,['onion']);
  assert.deepEqual(searchRequest.preference_prefer,[]);
  assert.deepEqual(searchRequest.preference_available,[]);
  assert.deepEqual(searchRequest.preference_avoid,[]);
  assert.deepEqual(searchRequest.bm25_categories,['vegetable','seafood']);
  assert.equal(searchRequest.query,'beef soup');
  getElement('query').value='salmon pasta';getElement('vector-query').value='Italian lunch with salmon and pasta';
  await getElement('search-form').listeners.submit({preventDefault(){}});
  assert.equal(searchRequest.bm25_query,'salmon pasta');assert.equal(searchRequest.vector_query,'Italian lunch with salmon and pasta');
  assert.equal(searchRequest.numeric_filters[0].operator,'lt');
  assert.equal(searchRequest.numeric_filters[1].value,500);
  getElement('retrieval-strategy').value='label_scope';getElement('scope-meal-types').value='lunch';getElement('scope-cuisines').value='italian';getElement('preference-available').value='salmon, pasta';getElement('bm25-available-boost').value='2';
  await getElement('search-form').listeners.submit({preventDefault(){}});
  assert.equal(searchRequest.retrieval_strategy,'text');assert.deepEqual(searchRequest.scope_meal_types,[]);assert.deepEqual(searchRequest.scope_cuisines,[]);assert.deepEqual(searchRequest.preference_available,['salmon','pasta']);assert.equal(searchRequest.bm25_available_boost,2);
  console.log('UI display, field isolation, stale-value clearing, query retention, manual edits and full search request passed');
})().catch(error => {console.error(error); process.exitCode=1;});
