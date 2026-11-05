import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../web',import.meta.url));
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--no-sandbox']});
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

const checks=[],retries=[];let retryFails=true;
await page.route('**/content/eligibility/**',async route=>{
 const body=route.request().postDataJSON();checks.push(body);
 const retry=Boolean(body.retry_run_id);if(retry)retries.push(body);
 if(retry&&retryFails)return route.fulfill({status:503,json:{detail:{message:'Simulated retry transport failure'}}});
 const partial=!body.local_only&&!retry;
 const done=retry;
 const ids=done?['1','2','3']:['1'];
 return route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:body.query,recipe_ids:body.recipe_ids},check_run_id:'e'.repeat(64),eligibility_id:done?'e'.repeat(64):null,partial,local_only:body.local_only,qualified_recipe_ids:ids,recipes,
 assessments:recipes.map((r,i)=>({recipe_id:r.recipe_id,status:i===0||done?'pass':'not_checked',reason:i===0?'Recorded requirements passed.':'This batch failed: Missing pending semantic conditions: hard-1',checks:i===0?[{kind:'ingredient',name:'beef',role:'required',decision:'pass',source:'local',evidence:['beef'],reason:'Recorded beef.'}]:[{kind:'category',name:'vegetable',role:'required',decision:done?'pass':'unknown',semantic_required:!done,source:done?'model':'local',evidence:done?['broccoli']:[],reason:done?'Broccoli is recorded.':'Pending category check.'}]})),
 constraint_counts:{pass:done?3:1,fail:0,unknown:0,not_checked:done?0:2},eligibility_stats:{target:20,batches:done?3:2,stop_reason:partial?'batch_failures':'candidate_pool_exhausted'},
 failed_batches:partial?[{batch_id:'batch-one',recipe_ids:['2','3'],errors:['Missing pending semantic conditions: hard-1']}]:[],check_ms:8,model_calls:[],new_model_call_count:retry?1:2,warnings:[]}});
});
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').click();await page.locator('#submit-button').click();await page.locator('#local-check-summary').filter({hasText:'Pending model checks'}).waitFor();
await page.locator('#stage-retrieval .stage-handoff button').click();await page.locator('#check-candidates').click();await page.locator('.retry-check-batch').waitFor();
assert.equal(await page.locator('[data-stage=check]').getAttribute('data-state'),'review');assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);assert.equal(await page.locator('#stage-check > .stage-handoff').isVisible(),false);
const passed=page.locator('[data-outcome=pass]');await passed.locator(':scope > summary').click();assert.match(await passed.innerText(),/Beef Soup One/);
await page.screenshot({path:'/tmp/check-batch-partial-desktop.png',fullPage:true});
await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:'/tmp/check-batch-partial-mobile.png',fullPage:true});
await page.locator('.retry-check-batch').click();await page.locator('#check-status').filter({hasText:'Simulated retry transport failure'}).waitFor();
assert.match(await passed.innerText(),/Beef Soup One/);assert.equal(await page.locator('.retry-check-batch').isEnabled(),true);
retryFails=false;await page.locator('.retry-check-batch').focus();await page.keyboard.press('Enter');await page.locator('#stage-check > .stage-handoff button').waitFor();
assert.equal(retries.length,2);assert.equal(retries[1].retry_run_id,'e'.repeat(64));assert.deepEqual(retries[1].retry_batch_ids,['batch-one']);assert.equal(await page.locator('.retry-check-batch').count(),0);assert.match(await page.locator('[data-outcome=pass] > summary').innerText(),/3\s+qualified/);
assert.equal(generations.length,0);await page.locator('#stage-check > .stage-handoff button').click();await page.locator('#generate-content').click();await page.locator('.generated-recipe').waitFor();assert.equal(generations.length,1);assert.equal(checks.length,4);
await page.locator('#user-query').fill('Changed request');assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);assert.equal(await page.locator('#check-output').innerText(),'');
assert.deepEqual(errors,[]);await browser.close();console.log('Batch recovery browser passed: partial results, disabled generation, selective retry, retry error preservation, keyboard, mobile, successful handoff and upstream invalidation.');
