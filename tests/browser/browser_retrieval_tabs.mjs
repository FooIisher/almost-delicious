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
const tab=k=>page.locator('#retrieval-tab-'+k),run=()=>page.locator('#submit-button').click();
const names=()=>page.locator('#results .recipe-title').allTextContents();
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').waitFor();await page.locator('#stage-intent > .stage-handoff button').click();
assert.equal(await tab('hybrid').getAttribute('aria-selected'),'true');
assert.equal(await page.locator('#retrieval-configuration').evaluate(el=>el.open),true);assert.equal(await page.locator('#retrieval-parameters').evaluate(el=>el.open),false);await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.waitForTimeout(350);const left=await page.locator('[data-parameter-branch=bm25]').boundingBox(),right=await page.locator('[data-parameter-branch=vector]').boundingBox();assert.equal(Math.round(left.y),Math.round(right.y));assert.ok(left.x<right.x);
await page.locator('#stage-retrieval').screenshot({path:'/tmp/retrieval-tabs-hybrid-setup.png'});
await run();await page.locator('#results .recipe-card').first().waitFor();assert.equal(await page.locator('#retrieval-parameters').evaluate(el=>el.open),false);assert.equal(await page.locator('#retrieval-research-details').evaluate(el=>el.open),false);assert.equal(await page.locator('#branch-flow-details').isVisible(),true);assert.equal(await page.locator('#branch-flow-details').evaluate(el=>!el.closest('#retrieval-research-details') && Boolean(el.compareDocumentPosition(document.getElementById('results'))&Node.DOCUMENT_POSITION_FOLLOWING)),true);assert.equal(await page.locator('#branch-flow-details').evaluate(el=>el.open),true);assert.equal(await page.evaluate(()=>Boolean(document.getElementById('branch-flow-details').compareDocumentPosition(document.getElementById('retrieval-parameters'))&Node.DOCUMENT_POSITION_FOLLOWING)),true);await page.locator('#stage-retrieval').screenshot({path:'/tmp/retrieval-flow-first.png'});assert.equal(requests.length,1);assert.equal(requests[0].mode,'hybrid');assert.equal(await page.locator('#stage-retrieval .stage-handoff').isVisible(),true);
await page.evaluate(()=>scrollTo(0,700));const beforeRefresh=await page.evaluate(()=>scrollY);await page.locator('#submit-button').evaluate(el=>el.click());await page.waitForTimeout(650);assert.ok(Math.abs((await page.evaluate(()=>scrollY))-beforeRefresh)<3,'Refresh preserves scroll');requests.pop();
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);const originalFlow=await page.locator('.fusion-output').innerText();
for(const branch of ['bm25','vector']){
 await tab(branch).click();assert.equal(await page.locator('#retrieval-flow').isVisible(),true);assert.equal(await page.locator('.branch-'+branch).isVisible(),true);assert.equal(await page.locator('.fusion-node').isVisible(),false);
 await tab('hybrid').click();assert.equal(await page.locator('#retrieval-flow').isVisible(),true);assert.equal(await page.locator('.branch-bm25').isVisible(),true);assert.equal(await page.locator('.branch-vector').isVisible(),true);assert.equal(await page.locator('.fusion-output').innerText(),originalFlow);assert.equal(await page.locator('#retrieval-flow').getAttribute('data-phase'),'complete');
}
assert.equal(requests.length,1,'Restoring a cached flow must not issue another search');
await page.getByRole('button',{name:'Save as baseline',exact:true}).click();await tab('bm25').click();assert.equal(await page.locator('.comparison-column').count(),2);assert.match(await page.locator('.comparison-totals').innerText(),/shared/);assert.match(await page.locator('.retrieval-comparison').innerText(),/Different retrieval modes/);await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('.retrieval-comparison').screenshot({path:'/tmp/retrieval-comparison-desktop.png'});assert.deepEqual(await names(),['Beef Soup Two','Beef Soup One']);assert.equal(requests.length,1);assert.equal(await page.locator('#stage-retrieval .stage-handoff').isVisible(),true);
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#query').fill('new beef soup');assert.match(await tab('hybrid').innerText(),/Needs refresh/);await run();await page.locator('#results .recipe-card').first().waitFor();assert.equal(requests.at(-1).mode,'bm25');assert.equal(requests.at(-1).bm25_query,'new beef soup');assert.equal(requests.at(-1).apply_preference_rerank,false);assert.equal(requests.length,2);
await page.locator('#stage-retrieval').screenshot({path:'/tmp/retrieval-tabs-bm25.png'});
await page.locator('#stage-retrieval .stage-handoff button').click();await checkThenGenerate(page);await page.locator('.generated-recipe').waitFor();assert.equal(generations.at(-1).retrieval_snapshot.mode,'bm25');assert.deepEqual(generations.at(-1).recipe_ids,['2','1']);await page.locator('[data-stage=retrieval]').click();
await tab('vector').click();assert.deepEqual(await names(),['Beef Soup One','Beef Soup Three']);assert.equal(requests.length,2);
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#vector-query').fill('new semantic beef soup');await page.locator('#vector-scope-weight').fill('0');await run();await page.locator('#results .recipe-card').first().waitFor();assert.equal(requests.at(-1).mode,'vector');assert.equal(requests.at(-1).vector_scope_weight,0);assert.equal(requests.length,3);
await tab('hybrid').click();assert.equal(await page.locator('#results').isVisible(),false);assert.match(await page.locator('.retrieval-tab-empty').innerText(),/Refresh/);
await run();await page.locator('#results .recipe-card').first().waitFor();assert.equal(requests.at(-1).mode,'hybrid');assert.equal(requests.at(-1).bm25_query,'new beef soup');assert.equal(requests.at(-1).vector_query,'new semantic beef soup');assert.equal(requests.at(-1).vector_scope_weight,0);assert.equal(requests.length,4);
await page.locator('#stage-retrieval .stage-handoff button').click();await checkThenGenerate(page);await page.locator('.generated-recipe').waitFor();await page.locator('[data-stage=retrieval]').click();await tab('bm25').click();await tab('hybrid').click();assert.equal(requests.length,4);assert.equal(await page.locator('.generated-recipe').count(),0);assert.equal(await page.locator('#stage-retrieval .stage-handoff').isVisible(),true);
// A fusion-only edit leaves the raw branch snapshots usable.
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#rrf-k').fill('12');await tab('vector').click();assert.deepEqual(await names(),['Beef Soup One','Beef Soup Three']);
// An interrupted request cannot replace another tab's list.
await tab('bm25').click();delay=300;await run();await page.waitForFunction(()=>document.getElementById('submit-button').disabled);await tab('vector').click();await page.waitForTimeout(450);assert.deepEqual(await names(),['Beef Soup One','Beef Soup Three']);
// Shared filters invalidate both branches and the fusion snapshot.
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#retrieval-parameters').evaluate(el=>el.open=true);await page.locator('#retrieval-configuration').evaluate(el=>el.open=true);await page.locator('#labels').fill('soup');assert.match(await tab('vector').innerText(),/Needs refresh/);assert.match(await tab('hybrid').innerText(),/Needs refresh/);
await page.setViewportSize({width:390,height:1000});await tab('hybrid').click();delay=0;await run();await page.locator('#results .recipe-card').first().waitFor();assert.equal(await page.locator('.comparison-column').count(),2);await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);assert.equal(await page.locator('.comparison-query').first().innerText(),'beef soup');assert.equal(await page.locator('.comparison-query').last().innerText(),'new beef soup');await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('.retrieval-comparison details').evaluate(el=>el.open=true);assert.match(await page.locator('.retrieval-comparison table').innerText(),/rrf_k/);assert.match(await page.locator('.retrieval-comparison table').innerText(),/vector_scope_weight/);assert.match(await page.locator('.comparison-recipe-id').first().innerText(),/Recipe ID:/);await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('.retrieval-comparison').screenshot({path:'/tmp/retrieval-comparison-mobile.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.locator('#stage-retrieval').screenshot({path:'/tmp/retrieval-tabs-mobile.png'});
await tab('bm25').focus();await page.keyboard.press('ArrowRight');assert.equal(await tab('vector').getAttribute('aria-selected'),'true');
// Relaxation freezes each actual strict branch as its own automatic baseline.
const relaxed=result({mode:'hybrid'});relaxed.relaxation={selected_plan:{actions:[{type:'drop_ingredient',value:'pineapple'}]}};
for(const branch of ['bm25','vector']){const raw=relaxed.branch_results[branch];raw.strict_baseline={status:'complete',candidate_count:1,elapsed_ms:12,results:raw.results.slice(0,1)};}
await page.evaluate(data=>RecipeRetrievalTabs.complete(data,{mode:'hybrid',query:'soup'}),relaxed);
for(const branch of ['bm25','vector']){
 await tab(branch).click();assert.match(await page.locator('.retrieval-comparison').innerText(),/Strict baseline/);assert.match(await page.locator('.comparison-column').first().innerText(),/Before relaxation/);assert.equal(await page.locator('.comparison-column').first().locator('li').count(),1);assert.equal(await page.locator('.comparison-column').last().locator('li').count(),2);assert.match(await page.locator('.comparison-totals').innerText(),/1 shared · 1 new/);assert.match(await page.locator('.retrieval-comparison').innerText(),/Remove required pineapple/);
}
await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('.retrieval-comparison').screenshot({path:'/tmp/relaxation-baseline-mobile.png'});
await page.setViewportSize({width:1440,height:1000});await tab('bm25').click();await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('.retrieval-comparison').screenshot({path:'/tmp/relaxation-baseline-desktop.png'});
await page.locator('#user-query').fill('New request');assert.equal(await page.locator('#results .recipe-card').count(),0);assert.deepEqual(errors,[]);
await browser.close();console.log('Retrieval tabs passed: raw branch order, independent runs, latest Hybrid settings, cache isolation, generation snapshot, abort/stale protection, shared invalidation, keyboard and mobile layout.');
