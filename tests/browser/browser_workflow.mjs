import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath as pathForQuery} from 'node:url';
function withQueries(data){const p=spawnSync(process.env.PYTHON_EXECUTABLE || pathForQuery(new URL('../../.venv/bin/python',import.meta.url)),['-c','import json,sys; from recipe_search.retrieval.query_builder import build_queries; p=json.load(sys.stdin); print(json.dumps(build_queries(p)))'],{cwd:pathForQuery(new URL('../..',import.meta.url)),input:JSON.stringify(data.parsed),encoding:'utf8'});if(p.status)throw new Error(p.stderr);return {...data,parsed:{...data.parsed,retrieval_queries:JSON.parse(p.stdout)}};}
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';
const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true,args:['--no-sandbox','--disable-gpu']});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
let query='Beef soup without vegetables',calls=0,generationRequest,generationFailure=false,comparisonMode=false,staleGeneration=false;
const extraction={intent:'recipe_search',search_text:'beef soup',dish_name:'beef soup',dish_type:'soup',meal_type:null,cuisine:null,
 target_evidence:{dish_name:'Beef soup',dish_type:'soup',meal_type:null,cuisine:null},ingredients:[
 {name:'beef',entity_type:'specific',role:'required',evidence:'Beef'},
 {name:'vegetable',entity_type:'category',role:'excluded',evidence:'vegetables'}],bounds:[],dietary_restrictions:[],soft_preferences:[],corrections:[],clarification_questions:[]};
const intent={token_usage:{input_tokens:1000,output_tokens:100,total_tokens:1100,cached_input_tokens:800},cost_estimate:{status:'estimated',estimated_usd:.00032,min_usd:.00032,max_usd:.00032,pricing_version:'2026-10-18',pricing_model:'gpt-4.1-mini',note:'Estimated standard API text-token cost.'},request_id:'test',raw_query:query,model:'mock-mini',provider:'openai_direct',prompt_version:'test',schema_version:'recipe-extraction-v4',intent_parse_ms:5,
 parsed:{...extraction,extraction,status:'ready',recipe_names:[],recipe_references:[],comparison_dimensions:[],missing_fields:[],uncertain_questions:[]},
 constraint_rows:extraction.ingredients.map(item=>({field:'ingredient_'+item.role,label:'Ingredient',value:[item.name],...item,support:item.entity_type==='category'?'unsupported':'supported'})),
 intent_scores:{},execution_support:'supported',context:{recipes:[]}};
const recipe={recipe_id:'2',document_id:'2',recipeid:2,name:'Recorded beef soup',description:'A recorded soup',ingredients:['beef'],recipecategory:['soup'],keywords:['beef','dinner','easy','weeknight','Mexican','comfort food','family meal','stove top'],rank:1,score:2,bm25_rank:1,vector_rank:1,bm25_contribution:.09,vector_contribution:.18,rrf_score:.27,aggregatedrating:4,total_time_minutes:25,calories:300,preference_evidence:[{group:'available',match_score:1,matched:['beef']},{group:'healthy',match_score:1,checks:[{field:'proteincontent',status:'met',value:25,unit:'g',operator:'gte',threshold:20}]}],display_image_url:'/assets/recipe-placeholder.svg'};
const data={type:'result',mode:'hybrid',effective_mode:'hybrid',execution:'parallel',result_count:1,results:[recipe],timings:{search_total_ms:2,bm25_recall_ms:1},branches:{bm25:{status:'complete',elapsed_ms:1},vector:{status:'complete',elapsed_ms:1}},candidate_counts:{bm25:1,vector:1,union:1,rrf:1},rrf:{k:10,bm25_boost:1,vector_boost:2}};
await page.route('**/health',route=>route.fulfill({json:{status:'ok'}}));
await page.route('**/intent/parse/*',async route=>{calls++;await route.fulfill({json:withQueries(intent)});});
await page.route('**/api/search/stream',route=>route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(data)+'\n\n'}));
await page.route('**/content/eligibility/*',route=>mockEligibility(route,[...data.results,{...recipe,recipe_id:'3'},{...recipe,recipe_id:'4'}]));
await page.route('**/content/generate/*',async route=>{
 if (generationFailure) {await route.fulfill({status:502,json:{detail:{message:'Simulated provider failure'}}});return;}
 generationRequest=route.request().postDataJSON().context;
 const generated = {token_usage:{input_tokens:1000,output_tokens:100,total_tokens:1100,cached_input_tokens:800},cost_estimate:{status:'estimated',estimated_usd:.00032,min_usd:.00032,max_usd:.00032},generation_context:{query:generationRequest.query,recipe_ids:generationRequest.recipe_ids},summary:'This soup is relevant, but the vegetable exclusion cannot be confirmed.',recommendations:[{recipe_id:'2',reason:'Beef soup; check its full ingredient list.'}],
 recipes:[{...recipe,recipe_id:'2',instructions:['Simmer the recorded ingredients.']}],assessments:[{recipe_id:'2',status:'pass',unresolved:[],checks:[{category:'vegetable',role:'excluded',status:'not_matched',reason:'No recorded category match.',evidence:[]}]}],
 warnings:[],model:'mock-flash',input_recipe_count:1,generation_ms:8,prompt_version:'test',usage:{total_tokens:100},model_input:{model:'mock-flash',input:{query,recipe_ids:['2']}}};
 generated.recommendations[0].brief_instructions = ['Simmer the recorded ingredients.'];
 generated.recommendations[0].flavor = 'Beef'; generated.recommendations[0].best_for = 'Soup dinner';
 if (comparisonMode) {
   generated.recipes.push({...recipe,recipe_id:'3',name:'Second soup'});
   generated.recommendations.push({recipe_id:'3',reason:'Another recorded soup.',brief_instructions:[],flavor:'Not specified',best_for:'An alternative'});
   generated.assessments.push({recipe_id:'3',status:'pass',unresolved:[],checks:[]});
 }
 if (staleGeneration) generated.generation_context.query = 'Previous stale query';
 await route.fulfill({json:generated});
});
await page.route('**/recipes/2',route=>route.fulfill({json:{...recipe,instructions:['Simmer.']}}));
if(process.env.WORKFLOW_STATIC==='1'){
 const fs=await import('node:fs/promises'),{fileURLToPath}=await import('node:url');const root=fileURLToPath(new URL('../../src/recipe_search/web',import.meta.url));
 await page.route('**/assets/**',async route=>{const file=new URL(route.request().url()).pathname.replace('/assets/','');try{await route.fulfill({body:await fs.readFile(root+'/'+file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/svg+xml'});}catch{await route.fulfill({status:404,body:''});}});
 await page.route('http://127.0.0.1:8003/',async r=>r.fulfill({body:await fs.readFile(root+'/index.html'),contentType:'text/html'}));
}
await page.goto(process.env.WORKFLOW_TEST_URL || 'http://127.0.0.1:8003');
await page.locator('#user-query').fill(query);
await page.locator('#submit-request').click();
await page.locator('#stage-intent > .stage-handoff button').waitFor();assert.equal(calls,1);
assert.equal(await page.locator('.request-composer #submit-request').count(),1);
assert.equal(await page.locator('.stage-heading-actions #intent-model').count(),1);
await page.locator('#stage-intent > .stage-handoff button').waitFor();
await page.locator('[data-stage="intent"] small').filter({hasText:'Complete'}).waitFor();
assert.equal(await page.locator('.workflow-nodes button:visible').count(),4);
assert.ok((await page.locator('.intent-usage-overview').innerText()).includes('1,100'));
assert.ok((await page.locator('.intent-usage-overview').innerText()).includes('$0.00032000'));
await page.screenshot({path:'/tmp/research-intent.png',fullPage:true,animations:'disabled'});
await page.locator('[data-stage="retrieval"]').click();
const headerBounds = await page.locator('#stage-retrieval .stage-heading').boundingBox();
const actionBounds = await page.locator('#submit-button').boundingBox();
assert.ok(actionBounds.x > headerBounds.x + headerBounds.width / 2, 'Retrieval action is at top right');
assert.ok(actionBounds.y < headerBounds.y + headerBounds.height, 'Retrieval action is in card header');
await page.screenshot({path:'/tmp/workflow-retrieval.png',fullPage:true});
await page.setViewportSize({width:375,height:812});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow at 375px');
await page.screenshot({path:'/tmp/workflow-retrieval-mobile.png',fullPage:true});
await page.emulateMedia({reducedMotion:'reduce'});
await page.setViewportSize({width:1280,height:900});
assert.equal(await page.locator('#include').inputValue(),'beef');
await page.locator('#retrieval-tab-hybrid').click();
await page.locator('#submit-button').click();
await page.locator('#results .recipe-card').waitFor();
await page.evaluate(()=>{RecipeRetrievalFlow.start('hybrid');RecipeRetrievalFlow.update({step:'bm25',status:'running'});RecipeRetrievalFlow.update({step:'vector',status:'running'});});
await page.waitForFunction(()=>document.querySelectorAll('.flow-node[aria-busy="true"]:not([hidden])').length===2);assert.equal(await page.locator('.flow-stage-card').count(),1);
assert.equal(await page.locator('#retrieval-flow').getAttribute('data-phase'),'running');
await page.screenshot({path:'/tmp/retrieval-flow-running.png',fullPage:true});
await page.evaluate(()=>{RecipeRetrievalFlow.start('hybrid');RecipeRetrievalFlow.complete({mode:'hybrid',effective_mode:'hybrid',branches:{bm25:{status:'complete',elapsed_ms:120,candidate_count:50},vector:{status:'complete',elapsed_ms:900,candidate_count:50}},candidate_counts:{bm25:50,vector:50,union:69,rrf:69},timings:{rrf_ms:.5},results:Array(20).fill({})});});
assert.ok((await page.locator('.fusion-output').innerText()).includes('69 unique candidates · 20 displayed'));
await page.waitForFunction(()=>document.querySelectorAll('.flow-links [data-flow="complete"]').length===3);
assert.equal(await page.locator('.flow-links [data-flow="running"]').count(),0);
await page.evaluate(async()=>{window.scrollTo(0,0);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
await page.screenshot({path:'/tmp/retrieval-flow-hybrid.png',fullPage:true,animations:'disabled'});
await page.setViewportSize({width:375,height:812});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.screenshot({path:'/tmp/retrieval-flow-mobile.png',fullPage:true,animations:'disabled'});
await page.setViewportSize({width:1280,height:900});
await page.evaluate(()=>{RecipeRetrievalFlow.start('hybrid');RecipeRetrievalFlow.complete({mode:'hybrid',effective_mode:'bm25',branches:{bm25:{status:'complete',elapsed_ms:120,candidate_count:50},vector:{status:'timeout',elapsed_ms:1000,candidate_count:0}},candidate_counts:{bm25:50,vector:0,union:50,rrf:50},timings:{rrf_ms:.5},results:Array(20).fill({})});});
assert.ok((await page.locator('.branch-vector').innerText()).includes('Timed out'));
assert.ok((await page.locator('.flow-caption').innerText()).includes('Degraded'));
await page.evaluate(()=>{RecipeRetrievalFlow.start('hybrid',{include:['beef'],exclude:['onion','garlic']});RecipeRetrievalFlow.complete({mode:'hybrid',effective_mode:'hybrid',branches:{bm25:{status:'complete',elapsed_ms:150,candidate_count:50},vector:{status:'complete',elapsed_ms:800,candidate_count:50}},candidate_counts:{bm25:50,vector:50,union:72,rrf:72},timings:{rrf_ms:.4},results:Array(20).fill({}),bm25_fallback:{triggered:true,used:true,status:'complete',threshold:5,initial_count:2,initial_ms:40,retry_count:50,retry_ms:110,original_include:['beef'],original_exclude:['onion','garlic']}});});
assert.equal(await page.locator('.fallback-node').count(),0);
assert.ok((await page.locator('.flow-constraints').first().innerText()).includes('onion, garlic'));
assert.ok((await page.locator('.output-bm25').innerText()).includes('50 recipes'));
assert.equal(await page.locator('.retry-output').count(),0);
await page.evaluate(async()=>{window.scrollTo(0,0);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
await page.screenshot({path:'/tmp/bm25-fallback-desktop.png',fullPage:true,animations:'disabled'});
await page.setViewportSize({width:375,height:812});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.screenshot({path:'/tmp/bm25-fallback-mobile.png',fullPage:true,animations:'disabled'});
await page.setViewportSize({width:1280,height:900});
await page.evaluate(value=>{RecipeRetrievalFlow.start('bm25');RecipeRetrievalFlow.complete(value);},data);

assert.ok(await page.locator('#results .recipe-card .card-copy > .description').first().isVisible());
assert.equal(await page.locator('#results .recipe-tag-row').count(),2);
assert.equal(await page.locator('#results .recipe-tag-row').nth(1).locator('.tag').count(),8);
assert.equal(await page.locator('#results .recipe-image .recipe-rank-badge').count(),1);
assert.equal(await page.locator('#results .card-meta .rank').count(),0);
await page.setViewportSize({width:375,height:812});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.screenshot({path:'/tmp/retrieval-info-mobile.png',fullPage:true});
await page.setViewportSize({width:1280,height:900});

assert.equal(await page.locator('#retrieval-configuration').evaluate(el=>el.open),false);
assert.ok(await page.locator('#retrieval-flow').isVisible());
assert.ok((await page.locator('.output-bm25').innerText()).includes('1 recipes'));
assert.equal(await page.locator('.fusion-node').isVisible(),false,'Unused RRF stage stays hidden');
await page.evaluate(async()=>{window.scrollTo(0,0);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
await page.screenshot({path:'/tmp/research-results.png',fullPage:true,animations:'disabled'});
generationFailure=true;
const handoff = page.locator('#stage-retrieval .stage-handoff');
assert.ok(await handoff.evaluate(el => Boolean(el.compareDocumentPosition(document.getElementById('results')) & Node.DOCUMENT_POSITION_FOLLOWING)));
await handoff.locator('button').click();await checkThenGenerate(page);
assert.equal(await page.locator('#stage-generation').isVisible(), true);
await page.locator('#generation-status').filter({hasText:'Simulated provider failure'}).waitFor();
generationFailure=false;
await page.locator('#generate-content').click();
await page.locator('.generated-recipe').waitFor();
assert.deepEqual(generationRequest.recipe_ids,['2']);
assert.equal(await page.locator('[data-stage="intent"]').getAttribute('data-backend-ms'),'5');
assert.equal(await page.locator('[data-stage="retrieval"]').getAttribute('data-backend-ms'),'2');
assert.equal(await page.locator('[data-stage="generation"]').getAttribute('data-backend-ms'),'8');
assert.equal(generationRequest.query,query);
assert.equal(await page.locator('.generation-usage-disclosure').evaluate(el=>el.open),false);
await page.locator('.generation-usage-disclosure > summary').click();
assert.ok((await page.locator('#generation-output .generation-usage').first().innerText()).includes('1,100'));
assert.ok((await page.locator('#generation-output .generation-usage').first().innerText()).includes('$0.00032000'));
await page.locator('.generation-usage-disclosure > summary').click();
assert.equal(generationRequest.retrieval_snapshot.mode,'hybrid');
assert.equal(await page.locator('.generated-recipe .search-warning').count(),0);
assert.match(await page.locator('.generated-photo').getAttribute('alt'), /not a recipe photograph/);
await page.locator('.matching-bubble').click();
assert.ok(await page.locator('.generation-recipe-notes').innerText().then(t => t.includes('Available ingredients: beef') && t.includes('Protein: 25 g') && t.includes('Rating 4 / 5')));
await page.locator('.matching-bubble').click();
await page.setViewportSize({width:375,height:812});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.screenshot({path:'/tmp/generation-cards-mobile.png',fullPage:true});
await page.setViewportSize({width:1440,height:1050});
await page.screenshot({path:'/tmp/workflow-generation.png',fullPage:true});
assert.equal(await page.locator('.generated-view').count(),0);
assert.equal(await page.locator('.generation-research').evaluate(el=>el.open),false);
await page.locator('.generation-research > summary').click();
await page.locator('.model-input-viewer summary').click();
assert.ok((await page.locator('.model-input-viewer pre').innerText()).includes('mock-flash'));
await page.locator('.generated-recipe .generated-visual').click();
await page.locator('#detail-panel .detail-card').waitFor();
await page.locator('.detail-close').click();
comparisonMode=true;
await page.evaluate(() => {
  // Exercise multiple displayed candidates without paying for model calls.
  window.comparisonToken = RecipeFlow.startRetrieval({query:'beef soup',mode:'bm25',size:20});
  RecipeFlow.retrievalComplete(window.comparisonToken, {results:[{recipe_id:'2',name:'Recorded beef soup'}, {recipe_id:'3',name:'Second soup'}]});
});
await finishCheck(page);await page.locator('#generate-content').click();
await page.locator('.recipe-comparison table').waitFor();
assert.equal(await page.locator('.recipe-comparison tbody tr').count(),2);
assert.equal(await page.locator('.recipe-essentials').first().evaluate(el=>el.open),false);
await page.locator('.recipe-essentials > summary').first().click();
assert.ok((await page.locator('.recipe-essentials').first().innerText()).includes('Simmer the recorded ingredients.'));
await page.setViewportSize({width:375,height:812});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.screenshot({path:'/tmp/recipe-answer-mobile.png',fullPage:true});
await page.setViewportSize({width:812,height:375});
await page.emulateMedia({reducedMotion:'reduce'});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.evaluate(()=>document.documentElement.style.fontSize='200%');
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
await page.evaluate(()=>document.documentElement.style.fontSize='');
await page.setViewportSize({width:1440,height:1050});
await page.evaluate(async()=>{await document.fonts.ready;window.scrollTo(0,0);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
await page.screenshot({path:'/tmp/recipe-answer-desktop.png',fullPage:true,animations:'disabled'});
comparisonMode=false;

await page.locator('[data-stage="retrieval"]').click();
assert.equal(await page.locator('#results .recipe-card').count(),0); // Replacing retrieval cleared the prior rendered list.
await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#retrieval-configuration').evaluate(el=>el.open=true);
await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#query').evaluate(el=>{for(let p=el.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});await page.locator('#query').fill('other soup');
assert.equal(await page.locator('[data-stage="generation"]').isDisabled(),true);
assert.equal(await page.locator('.generated-recipe').count(),0);
const previousQuery = query;
query = 'Chicken noodle soup';
intent.raw_query = query;
intent.parsed.search_text = 'chicken noodle soup'; intent.parsed.dish_name = 'chicken noodle soup';
intent.parsed.extraction.search_text = 'chicken noodle soup';
intent.parsed.extraction.dish_name = 'chicken noodle soup';
intent.parsed.extraction.ingredients = [{name:'chicken',entity_type:'specific',role:'required',evidence:'Chicken'}];
recipe.name = 'New chicken noodle soup'; recipe.ingredients = ['chicken'];
await page.locator('#user-query').fill(query);
await page.locator('#submit-request').click();
assert.equal(await page.locator('#generation-output').innerText(), '');
assert.equal(await page.locator('[data-stage="generation"]').getAttribute('data-backend-ms'),null);
await page.locator('#analyze-intent').click();
await page.locator('[data-stage="retrieval"]').click();
assert.equal(await page.locator('#include').inputValue(), 'chicken');
await page.locator('#retrieval-tab-hybrid').click();
await page.locator('#submit-button').click();
await page.locator('#results .recipe-card').waitFor();
await page.locator('#stage-retrieval .stage-handoff button').click();await checkThenGenerate(page);
await page.locator('.generated-recipe').waitFor();
assert.equal(generationRequest.query, query);
assert.equal(generationRequest.intent_snapshot.raw_query, query);
assert.equal(generationRequest.retrieval_snapshot.query, 'chicken noodle soup');
assert.ok((await page.locator('.generated-recipe .recipe-title').innerText()).includes('New chicken noodle soup'));
assert.ok(!(await page.locator('#generation-output').innerText()).includes('Recorded beef soup'));
staleGeneration=true;
await page.locator('#generate-content').click();
await page.locator('#generation-status').filter({hasText:'does not match this request'}).waitFor();
assert.equal(await page.locator('.generated-recipe').count(),0);
staleGeneration=false;
await page.locator('#generate-content').click();
await page.locator('.generated-recipe').waitFor();

await page.locator('#user-query').fill(query);
intent.parsed.status='needs_clarification';
intent.parsed.clarification_question='You asked to include vegetable and also exclude it. Should it be included or excluded?';
const previousInclude=await page.locator('#include').inputValue();
await page.locator('#submit-request').click();
await page.locator('[data-stage="intent"] small').filter({hasText:'Review required'}).waitFor();
assert.equal(await page.locator('[data-stage="retrieval"]').isDisabled(),true);
assert.equal(await page.locator('[data-stage="generation"]').isDisabled(),true);
assert.equal(await page.locator('#intent-panel').evaluate(el=>el.open),true);
assert.ok((await page.locator('#intent-content').innerText()).includes('Should it be included or excluded?'));
assert.equal(await page.locator('#include').inputValue(),previousInclude);
assert.equal(await page.locator('.generated-recipe').count(),0);
assert.equal(await page.locator('#results .recipe-card').count(),0);
intent.parsed.clarification_question=null;
intent.parsed.status='ready';
await page.locator('#analyze-intent').click();
await page.locator('[data-stage="retrieval"]').waitFor({state:'visible'});
await page.locator('[data-stage="retrieval"]').click();
data.results=[];data.result_count=0;
await page.locator('#submit-button').click();
await page.locator('#results .empty').waitFor({state:'visible'});
assert.equal(await page.locator('[data-stage="generation"]').isDisabled(),true);
data.results=[recipe];data.result_count=1;
await page.evaluate(() => {
 const original=window.fetch;
 window.fetch=async (...args) => {
   const response=await original(...args);
   if (window.delayedPath && String(args[0]).includes(window.delayedPath)) await new Promise(resolve=>{window.releaseResponse=resolve;});
   return response;
 };
 window.delayedPath='/intent/parse/';
});
await page.locator('#submit-request').click();
await page.waitForFunction(()=>Boolean(window.releaseResponse));
await page.locator('#user-query').fill('Changed request');
await page.evaluate(()=>{window.delayedPath=null;window.releaseResponse();window.releaseResponse=null;});
assert.equal(await page.locator('[data-stage="retrieval"]').isDisabled(),true);
await page.locator('#user-query').fill(query);
await page.locator('#submit-request').click();
await page.locator('#stage-intent > .stage-handoff button').waitFor();
await page.locator('[data-stage="retrieval"]').waitFor({state:'visible'});
await page.locator('[data-stage="retrieval"]').click();
await page.evaluate(()=>{window.delayedPath='/api/search/stream';});
await page.locator('#submit-button').click();
await page.waitForFunction(()=>Boolean(window.releaseResponse));
await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#retrieval-configuration').evaluate(el=>el.open=true);
await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#query').evaluate(el=>{for(let p=el.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});await page.locator('#query').fill('Changed retrieval query');
await page.evaluate(()=>{window.delayedPath=null;window.releaseResponse();window.releaseResponse=null;});
assert.equal(await page.locator('[data-stage="generation"]').isDisabled(),true);
assert.equal(await page.locator('#results').isVisible(),false);
await page.locator('#submit-button').click();
await page.locator('#results .recipe-card').waitFor({state:'visible'});
await finishCheck(page);await page.locator('[data-stage="generation"]').click();
await page.evaluate(()=>{window.delayedPath='/content/generate/';});
await page.locator('#generate-content').click();
await page.waitForFunction(()=>Boolean(window.releaseResponse));
await page.locator('#user-query').fill('New generation request');
await page.evaluate(()=>{window.delayedPath=null;window.releaseResponse();window.releaseResponse=null;});
assert.equal(await page.locator('.generated-recipe').count(),0);
// Semantic filtering uses the complete candidate pool, not just displayed Results.
query='Beef soup without vegetables'; intent.raw_query=query;
data.results=[recipe];data.result_count=1;data.generation_candidate_ids=['2','4'];
await page.route('**/content/generate/*',async route=>{
 const request=route.request().postDataJSON().context;generationRequest=request;
 const result={generation_context:{query:request.query,recipe_ids:request.recipe_ids},summary:'Here is a recorded soup.',recommendations:[{recipe_id:'2',reason:'A simple option with recorded beef.'}],
 recipes:[{...recipe,instructions:['Original recorded instruction.']},{...recipe,recipe_id:'4',name:'Unconfirmed soup'}],
 assessments:[{recipe_id:'2',status:'pass',unresolved:[],checks:[]},{recipe_id:'4',status:'unknown',unresolved:['vegetable'],checks:[{category:'vegetable',role:'excluded',status:'unknown',reason:'Incomplete ingredient information.',evidence:[]}]}],
 pending_recipe_ids:['4'],constraint_counts:{pass:1,fail:0,unknown:1},category_check_ms:50,summary_ms:40,
 warnings:[],model:'mock',input_recipe_count:2,generation_ms:100,prompt_version:'test',usage:{total_tokens:10},
 model_calls:[{phase:'category_check',model_input:{recipes:['2','4']},model_output:'{"assessments":[]}',elapsed_ms:50,usage:{total_tokens:5},prompt_version:'check'}]};
 await route.fulfill({contentType:'text/event-stream',body:[{type:'progress',phase:'category_check',completed:2,total:2,counts:{pass:1,fail:0,unknown:1}},{type:'result',data:result}].map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')});
});
await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').waitFor();
await page.locator('[data-stage="intent"] small').filter({hasText:'Complete'}).waitFor();
await page.locator('[data-stage="retrieval"]').click();await page.locator('#submit-button').click();await page.locator('#results .recipe-card').waitFor();
await finishCheck(page);await page.locator('[data-stage="generation"]').click();await page.locator('#generate-content').click();await page.locator('.generation-research > summary').click();await page.locator('.generation-pending').waitFor();
assert.deepEqual(generationRequest.recipe_ids,['2','4']);assert.equal(await page.locator('.generated-recipe').count(),1);
assert.ok((await page.locator('.generation-pending').innerText()).includes('Unconfirmed soup'));
await page.locator('.recipe-essentials > summary').click();
assert.ok((await page.locator('.generated-recipe').innerText()).includes('Original recorded instruction.'));
assert.equal(await page.locator('.matching-bubble').getAttribute('aria-expanded'),'false');
await page.locator('.matching-bubble').click();assert.equal(await page.locator('.matching-bubble').getAttribute('aria-expanded'),'true');
await page.setViewportSize({width:390,height:844});
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.screenshot({path:'/tmp/generation-semantic-mobile.png',fullPage:true});
await page.setViewportSize({width:1440,height:1050});await page.screenshot({path:'/tmp/generation-semantic-desktop.png',fullPage:true});
assert.equal(await page.locator('.generation-research').evaluate(el=>el.open),true);
assert.ok((await page.locator('.generation-research').innerText()).includes('Eligibility checks: 0.05 s'));
await page.locator('.generation-research > details').filter({has:page.locator('summary', {hasText:'Model call 1'})}).locator('summary').first().click();
await page.locator('.model-input-viewer').first().locator('summary').click();
await page.evaluate(()=>{navigator.clipboard.writeText=async text=>{window.copiedModelInput=text;};});
await page.getByRole('button',{name:'Copy input JSON',exact:true}).first().click();
assert.ok((await page.evaluate(()=>window.copiedModelInput)).includes('recipes'));
// A generated recipe remains inspectable when live ES detail reads fail.
await page.route('**/recipes/2',route=>route.fulfill({status:502,json:{detail:'Recipe detail lookup failed'}}));
await page.locator('.generated-visual').click();await page.locator('.detail-snapshot').waitFor();
assert.ok((await page.locator('#detail-panel').innerText()).includes('Original recorded instruction.'));
assert.ok((await page.locator('#detail-panel').innerText()).includes('Saved generation snapshot'));
await page.locator('.detail-close').click();
await page.route('**/recipes/4',route=>route.fulfill({status:502,json:{detail:'Recipe detail lookup failed'}}));
await page.locator('.generation-pending .recipe-title').click();await page.locator('.detail-snapshot').waitFor();
assert.ok((await page.locator('#detail-panel').innerText()).includes('Unconfirmed soup'));await page.locator('.detail-close').click();
await page.route('**/recipes/999',route=>route.fulfill({status:404,json:{detail:'Recipe not found'}}));
await page.evaluate(()=>loadRecipeDetail('999',document.getElementById('generate-content'),{recipe_id:'2',name:'Wrong snapshot'}));
assert.equal(await page.locator('.detail-snapshot').count(),0);assert.ok((await page.locator('#detail-panel').innerText()).includes('Could not load recipe details'));await page.locator('.detail-close').click();
// All selected recipes filtered out is a completed generation, not an error.
await page.route('**/content/generate/*',async route=>{
 const request=route.request().postDataJSON().context;
 const result={generation_context:{query:request.query,recipe_ids:request.recipe_ids},summary:'No confirmed recommendations are available from this selection.',recommendations:[],
 recipes:[{...recipe,recipe_id:'2'},{...recipe,recipe_id:'4'}],assessments:[{recipe_id:'2',status:'fail',unresolved:[],checks:[{category:'vegetable',role:'excluded',status:'matched',evidence:['onion'],reason:'Onion is a vegetable.'}]},{recipe_id:'4',status:'unknown',unresolved:['vegetable'],checks:[{category:'vegetable',role:'excluded',status:'unknown',evidence:[],reason:'Incomplete ingredients.'}]}],
 pending_recipe_ids:['4'],constraint_counts:{pass:0,fail:1,unknown:1},warnings:['One model-selected recipe was filtered.'],model:'mock',input_recipe_count:2,generation_ms:100,prompt_version:'test',usage:{total_tokens:10},selection_counts:{requested:5,available:2,category_eligible:0,model_selected:1,filtered:1,recommended:0}};
 await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'result',data:result})+'\n\n'});
});
await page.locator('#generate-content').click();
await page.locator('[data-stage="generation"] small').filter({hasText:'Complete'}).waitFor();
assert.equal(await page.locator('.generated-recipe').count(),0);
assert.ok((await page.locator('.generated-summary').innerText()).includes('No confirmed recommendations'));
assert.equal(await page.locator('.generation-pending').count(),1);
// Requests without a dish target automatically use shared label scope.
query='Got some canned salmon and pasta in the pantry. Looking for a high-protein, 15-minute lunch with Italian flavors, but no dairy or heavy cream, please.';
intent.raw_query=query;Object.assign(intent.parsed,{status:'ready',dish_name:null,dish_type:null,meal_type:'lunch',cuisine:'italian',search_text:'Italian lunch with canned salmon and pasta'});
Object.assign(intent.parsed.extraction,{dish_name:null,dish_type:null,meal_type:'lunch',cuisine:'italian',search_text:'Italian lunch with canned salmon and pasta',ingredients:[{name:'canned salmon',role:'available',entity_type:'specific',evidence:'canned salmon'},{name:'pasta',role:'available',entity_type:'specific',evidence:'pasta'},{name:'dairy',role:'excluded',entity_type:'category',evidence:'dairy'}]});
intent.constraint_rows=[];
let scopeRequest;
await page.route('**/api/search/stream',route=>{
 scopeRequest=route.request().postDataJSON();const scoped={...data,preferences:{preference_lambda:.3,rating_boost:.1},rrf:{k:10,bm25_boost:1,vector_boost:2},results:[{...recipe,bm25_rank:1,vector_rank:1,bm25_contribution:.09,vector_contribution:.18,rrf_score:.27,rrf_rank:1,normalized_rrf:1,final_score:1,preference_score:0,preference_evidence:[]}],mode:scopeRequest.mode,effective_mode:scopeRequest.mode,retrieval_strategy:scopeRequest.retrieval_strategy,query_role:scopeRequest.mode==='bm25'?'unused':'vector_only',candidate_counts:{bm25:10,vector:10,union:15,rrf:15},branches:{bm25:{status:'complete',elapsed_ms:1,candidate_count:10},vector:{status:'complete',elapsed_ms:1,candidate_count:10}},effective_filters:{...scopeRequest},bm25_fallback:{triggered:false,used:false,initial_count:10,initial_ms:1,original_include:scopeRequest.include_ingredients,original_exclude:scopeRequest.exclude_ingredients}};
 route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({...scoped,type:'result'})+'\n\n'});
});
await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').waitFor();
await page.locator('[data-stage="intent"] small').filter({hasText:'Complete'}).waitFor();await page.locator('[data-stage="retrieval"]').click();
assert.equal(await page.locator('#retrieval-strategy').inputValue(),'text');
assert.equal(await page.locator('#meal-type-target').inputValue(),'lunch');assert.equal(await page.locator('#cuisine-target').inputValue(),'italian');
assert.equal(await page.locator('#preference-available').inputValue(),'canned salmon, pasta');assert.equal(await page.locator('#include').inputValue(),'');assert.equal(await page.locator('#exclude').inputValue(),'');
assert.equal(await page.locator('#query-label').textContent(),'BM25 query');
await page.locator('#retrieval-tab-hybrid').click();await page.locator('#submit-button').click();
try {await page.locator('#results .recipe-card').waitFor({timeout:5000});} catch(error) {throw new Error((await page.locator('#results').textContent())+' '+JSON.stringify(await page.locator('#search-form :invalid').evaluateAll(items=>items.map(x=>({id:x.id,value:x.value})))));}
assert.deepEqual(scopeRequest.scope_meal_types,[]);assert.deepEqual(scopeRequest.scope_cuisines,[]);assert.deepEqual(scopeRequest.preference_available,['canned salmon','pasta']);assert.equal(scopeRequest.bm25_available_boost,2);
await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#retrieval-configuration').evaluate(el=>el.open=true);
await page.locator('#cuisine-target').evaluate(el=>{for(let p=el.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});await page.locator('#cuisine-target').fill('mediterranean');await page.locator('#cuisine-role').selectOption('required');
assert.match(await page.locator('#final-cuisine-status').innerText(),/must confirm/);
await page.locator('#submit-button').click();await page.locator('#results .recipe-card').waitFor();assert.equal(scopeRequest.cuisine_target,'mediterranean');assert.equal(scopeRequest.retrieval_strategy,'text');
await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#retrieval-configuration').evaluate(el=>el.open=true);await page.locator('#retrieval-tab-vector').click();assert.equal(await page.locator('#vector-query').evaluate(el=>el.required),true);
await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.screenshot({path:'/tmp/layered-settings-mobile.png',fullPage:true});await page.setViewportSize({width:1440,height:1050});await page.screenshot({path:'/tmp/layered-settings-desktop.png',fullPage:true});
assert.deepEqual(errors,[]);
console.log('Browser workflow passed: all stages, error/retry, details, unknown warning, clarification/no-results gates, state retention and stale response rejection.');
await page.setViewportSize({width:390,height:844});
await page.screenshot({path:'/tmp/workflow-mobile.png',fullPage:true});
await browser.close();
