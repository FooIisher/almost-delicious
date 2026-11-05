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
const localRequests=[],checkRequests=[],summaryRequests=[];
let failCheck=false,failSummary=false,slowCheck=false;
await page.route('**/content/eligibility/**',async route=>{
 const body=route.request().postDataJSON();(body.local_only?localRequests:checkRequests).push({body,url:route.request().url()});
 if(!body.local_only&&slowCheck)await new Promise(r=>setTimeout(r,300));
 if(!body.local_only&&failCheck)return route.fulfill({status:502,json:{detail:{message:'Simulated semantic check failure',model_calls:[]}}});
 const data={eligibility_id:body.local_only?null:'b'.repeat(64),local_only:body.local_only,cache_hit:false,check_ms:7,
 generation_context:{query:body.query,recipe_ids:body.recipe_ids},qualified_recipe_ids:body.local_only?['1','2']:['1','2','3'],recipes,
 assessments:recipes.map((r,i)=>({recipe_id:r.recipe_id,status:body.local_only&&i===2?'not_checked':'pass',checks:[],unresolved:[]})),
 constraint_counts:{pass:body.local_only?2:3,fail:0,unknown:0,not_checked:body.local_only?1:0},eligibility_stats:{target:20,processed:body.local_only?2:3,total:3,batches:body.local_only?0:1,stop_reason:'candidate_pool_exhausted'},
 model:'mock-check',model_calls:body.local_only?[]:[{phase:'category_check',recipe_ids:['3'],model_input:{recipes:[]},model_output:{assessments:[]},usage:{},prompt_version:'check-test'}],warnings:[],usage:{}};
 try{return await route.fulfill({json:data});}catch{}
});
await page.route('**/content/generate/**',async route=>{
 const request=route.request().postDataJSON();summaryRequests.push({body:request,url:route.request().url()});
 if(failSummary)return route.fulfill({status:502,json:{detail:{message:'Simulated summary failure',model_calls:[]}}});
 const data={schema_version:'recipe-generation-v13',eligibility_id:request.eligibility_id,generation_context:{query:request.context.query,recipe_ids:request.context.recipe_ids},
 summary:'Here are beef soup options from the qualified pool.',recommendations:[{recipe_id:'1',reason:'Recorded beef and soup match your request.',flavor:'Beef',best_for:'Dinner'}],recipes,
 assessments:recipes.map(r=>({recipe_id:r.recipe_id,status:'pass',checks:[],unresolved:[]})),constraint_counts:{pass:3,fail:0,unknown:0,not_checked:0},recheck_stats:{enabled:request.recheck,checked:1,overturned:[]},
 eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},model:'mock-summary',generation_ms:9,model_calls:[{phase:'summary',recipe_ids:['1'],model_input:{},model_output:{},usage:{}}],usage:{},warnings:[]};
 return route.fulfill({json:data});
});
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();
await page.locator('#stage-intent > .stage-handoff button').click();assert.equal(await page.locator('.workflow-nodes button').count(),4);
await page.locator('#submit-button').click();await page.locator('#local-check-summary').filter({hasText:'Pending model checks 1'}).waitFor();
assert.equal(await page.locator('#stage-retrieval .stage-handoff').evaluate(el=>el.previousElementSibling.classList.contains('stage-heading')),true);await page.locator('#stage-retrieval').screenshot({path:'/tmp/retrieval-top-handoff.png'});assert.equal(checkRequests.length,0);assert.equal(summaryRequests.length,0);assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);
await page.locator('#stage-retrieval .stage-handoff button').click();assert.equal(checkRequests.length,0);
await page.screenshot({path:'/tmp/recipe-check-local-desktop.png',fullPage:true});
failCheck=true;await page.locator('#check-candidates').click();await page.locator('#check-status').filter({hasText:'Simulated semantic check failure'}).waitFor();
assert.equal(summaryRequests.length,0);assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);
failCheck=false;await page.locator('#check-candidates').click();await page.locator('#stage-check > .stage-handoff button').waitFor();
assert.equal(await page.locator('[data-stage=check]').getAttribute('data-backend-ms'),'7');assert.equal(summaryRequests.length,0);
assert.equal(checkRequests.length,2);assert.equal(await page.locator('.check-research').evaluate(el=>el.open),false);
await page.screenshot({path:'/tmp/recipe-check-complete-desktop.png',fullPage:true});
await page.locator('#stage-check > .stage-handoff button').click();assert.equal(summaryRequests.length,0);
await page.locator('#generation-model').selectOption('gpt41-mini');await page.locator('#generate-content').click();await page.locator('.generated-recipe').waitFor();
assert.equal(checkRequests.length,2);assert.equal(summaryRequests.length,1);assert.equal(summaryRequests[0].body.eligibility_id,'b'.repeat(64));
assert.equal(summaryRequests[0].body.recipe_ids,undefined);assert.equal(summaryRequests[0].body.recheck,false);assert.equal(await page.locator('[data-stage=generation]').getAttribute('data-backend-ms'),'9');
await page.locator('#generation-model').selectOption('gpt41-nano');assert.equal(await page.locator('.generated-recipe').count(),0);
assert.equal(await page.locator('#generation-recheck').count(),0);assert.equal(await page.locator('.generation-advanced').count(),0);assert.doesNotMatch(await page.locator('#stage-generation').innerText(),/Recheck semantic decisions|Unconfirmed category constraints|Semantic recheck:/);
failSummary=true;await page.locator('#generate-content').click();await page.locator('#generation-status').filter({hasText:'Simulated summary failure'}).waitFor();
assert.equal(checkRequests.length,2);failSummary=false;await page.locator('#generate-content').click();await page.locator('.generated-recipe').waitFor();
assert.equal(checkRequests.length,2);assert.equal(summaryRequests.at(-1).body.recheck,false);assert.match(summaryRequests.at(-1).url,/gpt41-nano/);
await page.screenshot({path:'/tmp/split-generation-desktop.png',fullPage:true});
await page.locator('[data-stage=check]').click();await page.locator('#check-model').selectOption('gpt41-mini');await page.locator('#check-status').filter({hasText:'Local checks complete'}).waitFor();
assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);assert.equal(await page.locator('#generation-output').innerText(),'');
await page.setViewportSize({width:390,height:844});await page.locator('#check-candidates').click();await page.locator('#stage-check > .stage-handoff button').waitFor();
assert.match(checkRequests.at(-1).url,/gpt41-mini/);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
await page.screenshot({path:'/tmp/recipe-check-mobile.png',fullPage:true});
slowCheck=true;await page.locator('#check-candidates').click();await page.waitForTimeout(60);await page.locator('#user-query').fill('Changed request');
await page.waitForTimeout(400);assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);assert.equal(await page.locator('#stage-check > .stage-handoff').isVisible(),false);assert.equal(await page.locator('#check-output').innerText(),'');
assert.deepEqual(errors,[]);await browser.close();console.log('Four-stage browser passed: local-only preview, explicit checks and summary, model independence, no semantic recheck UI, failures/retry, upstream invalidation, stale response isolation, desktop/mobile.');
