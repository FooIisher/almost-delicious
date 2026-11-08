import {verifyVerticalFlow} from './vertical_flow_helpers.mjs';
import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../src/recipe_search/web',import.meta.url));
const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],generations=[];
page.on('pageerror',error=>errors.push(error.message));
const query='Find beef soup for dinner.';
const extraction={intent:'recipe_search',search_text:'beef soup',dish_name:null,dish_type:'soup',meal_type:'dinner',meal_type_role:'required',cuisine:null,cuisine_role:null,target_evidence:{dish_name:null,dish_type:'soup',meal_type:'dinner',cuisine:null},ingredients:[{name:'beef',role:'required',entity_type:'specific',evidence:'beef'}],required_expression:null,bounds:[],soft_preferences:[],dietary_restrictions:[],generation_notes:[],corrections:[],clarification_questions:[]};
const intent={request_id:'mock',raw_query:query,model:'mock-flash',schema_version:'recipe-extraction-v7',provider:'deepseek_direct',intent_parse_ms:4,parsed:{...extraction,extraction,status:'ready',recipe_names:[],recipe_references:[],comparison_dimensions:[],missing_fields:[],uncertain_questions:[],retrieval_queries:{bm25_query:'beef soup',vector_query:'Hearty beef soup',vector_scope_query:'Beef soup for dinner',source:'Required ingredients + Dish type'}},constraint_rows:[],intent_scores:{},execution_support:'supported',context:{recipes:[]}};
const recipes=[1,2,3].map((id,i)=>({recipe_id:String(id),document_id:String(id),name:['Beef Soup One','Beef Soup Two','Beef Soup Three'][i],ingredients:['beef'],instructions:['Simmer source ingredients.'],description:'Recorded recipe.',keywords:['soup','dinner'],recipecategory:['soup'],total_time_minutes:25,aggregatedrating:4,score:.9-i*.1,rank:i+1,match_highlights:{}}));
recipes[0].ingredients=['beef','tomatoes','green onions','ground chicken','plain fat-free yogurt','fresh coriander','fresh ginger','curry','dried coriander','cumin','cayenne','salt'];
let delay=0;
const ids=list=>list.map(r=>r.recipe_id);
function result(body){
 const bm=[recipes[1],recipes[0]].map((r,i)=>({...r,rank:i+1,score:10-i}));
 const vec=[recipes[0],recipes[2]].map((r,i)=>({...r,rank:i+1,score:.9-i*.1,semantic_similarity:.8-i*.2}));
 const hybrid=recipes.map((r,i)=>({...r,rank:i+1,rrf_rank:i+1,bm25_rank:i===2?null:i+1,vector_rank:i===1?null:i+1,bm25_contribution:.05,vector_contribution:.1,rrf_score:.15,normalized_rrf:.9-i*.1,final_score:1-i*.1,preference_score:.2,preference_evidence:[]}));
 const rows=body.mode==='hybrid'?hybrid:body.mode==='bm25'?bm:vec;
 return {type:'result',mode:body.mode,effective_mode:body.mode,execution:body.execution||'parallel',results:rows,result_count:rows.length,original_conditions:body,effective_filters:body,
   branch_results:{...(body.mode!=='vector'?{bm25:{status:'complete',candidate_count:2,results:bm,generation_candidate_ids:ids(bm)}}:{}),...(body.mode!=='bm25'?{vector:{status:'complete',candidate_count:2,results:vec,generation_candidate_ids:ids(vec)}}:{})},
   generation_candidate_ids:ids(rows),candidate_counts:{bm25:body.mode==='vector'?0:2,vector:body.mode==='bm25'?0:2,union:3,rrf:body.mode==='hybrid'?3:null},
   rrf:body.mode==='hybrid'?{k:10,bm25_boost:1,vector_boost:2}:null,preferences:body.mode==='hybrid'?{preference_lambda:.3,rating_boost:.1}:null,
   branches:{...(body.mode!=='vector'?{bm25:{status:'complete',elapsed_ms:12,candidate_count:2}}:{}),...(body.mode!=='bm25'?{vector:{status:'complete',elapsed_ms:20,candidate_count:2}}:{})},
   timings:{search_total_ms:24,bm25_recall_ms:12,vector_recall_ms:20,rrf_ms:1},match_result_size:{value:3,relation:'eq'},bm25_fallback:{triggered:false,used:false,initial_count:2,initial_ms:12},warnings:[],executed_queries:{}};
}
await page.route('**/*',async route=>{
 const path=new URL(route.request().url()).pathname;
 if(path==='/health')return route.fulfill({json:{status:'ok'}});
 if(path.startsWith('/intent/parse/'))return route.fulfill({json:intent});
 if(path==='/api/search/stream'){
  const body=route.request().postDataJSON();requests.push(body);const wait=delay;delay=0;
  if(wait)await new Promise(r=>setTimeout(r,wait));
  try{return await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(result(body))+'\n\n'});}catch{return;}
 }
 if(path.startsWith('/content/eligibility/'))return mockEligibility(route,recipes);
 if(path.startsWith('/content/generate/')){
  const body=route.request().postDataJSON().context;generations.push(body);const generatedRecipes=recipes.filter(r=>body.recipe_ids.includes(r.recipe_id));return route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:body.query,recipe_ids:body.recipe_ids},summary:'Here are beef soups for your request.',recommendations:[{recipe_id:'1',reason:'Recorded beef and soup match your request.',flavor:'Beef',best_for:'Dinner'}],recipes:generatedRecipes,assessments:generatedRecipes.map(r=>({recipe_id:r.recipe_id,status:'pass',checks:[],unresolved:[]})),constraint_counts:{pass:3,fail:0,unknown:0,not_checked:0},model:'mock-flash',generation_ms:9,usage:{},warnings:[],model_calls:[]}});
 }
 if(path.startsWith('/recipes/'))return route.fulfill({json:recipes[0]});
 const file=path==='/'?'index.html':path.replace('/assets/','');try{return route.fulfill({body:await fs.readFile(root+'/'+file),contentType:file.endsWith('.html')?'text/html':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/svg+xml'});}catch{return route.fulfill({status:404,body:''});}
});


await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').click();
await page.locator('#submit-button').click();await page.locator('#results .recipe-card').first().waitFor();
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#branch-flow-details').evaluate(el=>el.open=true);
const send=async event=>page.evaluate(e=>RecipeRetrievalFlow.update(e),event);
const visible=()=>page.locator('#retrieval-flow .flow-node:visible').count();
await page.evaluate(()=>RecipeRetrievalFlow.start('hybrid',{execution:'parallel',include:['beef']}));
assert.equal(await visible(),1);assert.equal(await page.locator('.unified-decision').count(),0);assert.equal(await page.locator('.unified-relaxed-bm25').count(),0);await page.locator('.unified-preparing').waitFor();assert.equal(await page.locator('.fusion-node').isVisible(),false);
await send({step:'relaxation_statistics',status:'running'});assert.equal(await page.locator('.unified-decision').isVisible(),false);
await send({step:'bm25',status:'running'});await send({step:'vector',status:'running'});
assert.equal(await visible(),2);assert.equal(await page.locator('.flow-stage-card').count(),1);assert.equal(await page.locator('.flow-execution-label').innerText(),'Parallel');assert.equal(await page.locator('.branch-bm25').getAttribute('aria-busy'),'true');assert.equal(await page.locator('.branch-vector').getAttribute('aria-busy'),'true');
assert.equal(await page.locator('.output-bm25').isVisible(),false);assert.equal(await page.locator('.unified-merged').isVisible(),false);
await page.locator('#retrieval-flow').scrollIntoViewIfNeeded();
await verifyVerticalFlow(page);await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/progressive-flow-running-desktop.png'});
await send({step:'bm25',status:'complete',elapsed_ms:335.04,candidate_count:0});
assert.equal(await page.locator('.branch-bm25').getAttribute('aria-busy'),'false');assert.match(await page.locator('.output-bm25').innerText(),/0 recipes/);
assert.equal(await page.locator('.unified-strict-check').isVisible(),false);assert.equal(await page.locator('.branch-vector').getAttribute('aria-busy'),'true');
await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/progressive-flow-partial-desktop.png'});
await page.setViewportSize({width:390,height:844});await verifyVerticalFlow(page);await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/progressive-flow-running-mobile.png'});
await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('.branch-vector .flow-step-state svg').evaluate(n=>getComputedStyle(n).animationName),'none');assert.match(await page.locator('.branch-vector').innerText(),/Retrieving/);
await page.setViewportSize({width:1440,height:1000});await page.emulateMedia({reducedMotion:'no-preference'});
await send({step:'vector',status:'complete',elapsed_ms:9130,candidate_count:6});await send({step:'strict_candidate_check',status:'complete',candidate_count:6,threshold:10});
assert.equal(await page.locator('.unified-decision').getAttribute('aria-busy'),'true');assert.equal(await page.locator('.unified-relaxed-bm25').isVisible(),false);
await send({step:'relaxation_decision',status:'complete',plan:{plan_id:'test'}});
assert.equal(await page.locator('.unified-relaxed-bm25').isVisible(),false);
await send({step:'relaxed_bm25',status:'running'});assert.equal(await page.locator('.unified-relaxed-bm25-output').isVisible(),false);assert.equal(await page.locator('.unified-relaxed-vector').isVisible(),false);
await send({step:'relaxed_bm25',status:'complete',elapsed_ms:1490,candidate_count:10,added:10});await send({step:'relaxed_vector',status:'running'});
assert.match(await page.locator('.unified-relaxed-bm25-output').innerText(),/10 returned · 10 new/);assert.equal(await page.locator('.fusion-node').isVisible(),false);
await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/progressive-flow-relaxing-desktop.png'});
await send({step:'relaxed_vector',status:'complete',elapsed_ms:2140,candidate_count:10,added:9});await send({step:'candidate_merge',status:'complete',candidate_count:25});await send({step:'rrf',status:'running'});
assert.equal(await page.locator('.fusion-node').getAttribute('aria-busy'),'true');assert.equal(await page.locator('.fusion-output').isVisible(),false);
await send({step:'rrf',status:'complete',elapsed_ms:.14,candidate_count:25});assert.equal(await page.locator('.fusion-output').getAttribute('aria-busy'),'true');
const data=result({mode:'hybrid',execution:'parallel'});data.branches={bm25:{status:'complete',elapsed_ms:335.04,candidate_count:10},vector:{status:'complete',elapsed_ms:9130,candidate_count:16}};
await page.evaluate(value=>RecipeRetrievalFlow.complete(value),data);assert.equal(await page.locator('.fusion-output').getAttribute('aria-busy'),'false');await verifyVerticalFlow(page);
// Sufficient strict recall must not mount a relaxation decision or extra branches.
await page.evaluate(()=>RecipeRetrievalFlow.start('hybrid'));await send({step:'bm25',status:'running'});await send({step:'bm25',status:'complete',elapsed_ms:10,candidate_count:12});await send({step:'vector',status:'running'});await send({step:'vector',status:'complete',elapsed_ms:20,candidate_count:12});await send({step:'strict_candidate_check',status:'complete',candidate_count:20,threshold:10});await send({step:'relaxation_statistics',status:'complete'});await send({step:'relaxation_decision',status:'strict_sufficient'});assert.equal(await page.locator('.unified-decision').count(),0);assert.equal(await page.locator('.flow-stage-card[data-stage=additional]').count(),0);
// Decision without relaxation goes directly into fusion; no supplemental placeholders.
await send({step:'strict_candidate_check',status:'complete',candidate_count:2,threshold:10});await send({step:'relaxation_decision',status:'no_plan'});await send({step:'candidate_merge',status:'complete',candidate_count:20});await send({step:'rrf',status:'complete',elapsed_ms:1,candidate_count:20});
assert.equal(await page.locator('.flow-stage-card[data-stage=additional]').count(),0);assert.match(await page.locator('.unified-decision').innerText(),/No relaxation/);await verifyVerticalFlow(page);
await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/horizontal-no-relaxation.png'});
const toggle=page.locator('.flow-collapse-toggle');await toggle.click();assert.equal(await page.locator('.flow-viewport').isVisible(),false);assert.equal(await toggle.getAttribute('aria-expanded'),'false');
await send({step:'rrf',status:'complete',elapsed_ms:2,candidate_count:20});await toggle.press('Enter');assert.equal(await page.locator('.flow-viewport').isVisible(),true);assert.equal(await toggle.getAttribute('aria-expanded'),'true');
// A new run must erase old results immediately, and failure cannot expose future steps.
await page.evaluate(()=>RecipeRetrievalFlow.start('bm25'));
assert.equal(await visible(),1);await send({step:'bm25',status:'running'});await page.evaluate(()=>RecipeRetrievalFlow.fail());
assert.match(await page.locator('.branch-bm25').innerText(),/Failed/);assert.equal(await page.locator('.fusion-output').isVisible(),false);
await page.evaluate(()=>RecipeRetrievalFlow.clear());assert.equal(await page.locator('#retrieval-flow').isVisible(),false);
// Sequential mode reveals Vector only when its real start event arrives.
await page.evaluate(()=>RecipeRetrievalFlow.start('hybrid',{execution:'serial'}));await send({step:'bm25',status:'running'});assert.equal(await page.locator('.branch-vector').isVisible(),false);
await send({step:'bm25',status:'complete',elapsed_ms:15,candidate_count:2});await send({step:'vector',status:'running'});assert.equal(await page.locator('.branch-vector').isVisible(),true);
assert.match(await page.locator('.flow-caption').innerText(),/Sequential/);assert.deepEqual(errors,[]);
await browser.close();console.log('Progressive horizontal dependency flow passed: real-event reveal, no future placeholders, counts, spinners, serial/parallel, relaxation, RRF, reset/failure, reduced motion and mobile.');
