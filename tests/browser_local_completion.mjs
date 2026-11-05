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
   generation_candidate_ids:candidateRecipes.map(r=>r.recipe_id),candidate_counts:{bm25:body.mode==='vector'?0:2,vector:body.mode==='bm25'?0:2,union:3,rrf:body.mode==='hybrid'?3:null},
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
  const body=route.request().postDataJSON().context;generations.push(body);const generatedRecipes=recipes.filter(r=>body.recipe_ids.includes(r.recipe_id));return route.fulfill({json:{schema_version:'recipe-generation-v11',generation_context:{query:body.query,recipe_ids:body.recipe_ids},summary:'Here are beef soups for your request.',recommendations:[{recipe_id:'1',reason:'Recorded beef and soup match your request.',flavor:'Beef',best_for:'Dinner'}],recipes:generatedRecipes,assessments:generatedRecipes.map(r=>({recipe_id:r.recipe_id,status:'pass',checks:[],unresolved:[]})),constraint_counts:{pass:3,fail:0,unknown:0,not_checked:0},model:'mock-flash',generation_ms:9,usage:{},warnings:[],model_calls:[]}});
 }
 if(path.startsWith('/recipes/'))return route.fulfill({json:recipes[0]});
 const file=path==='/'?'index.html':path.replace('/assets/','');try{return route.fulfill({body:await fs.readFile(root+'/'+file),contentType:file.endsWith('.html')?'text/html':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/svg+xml'});}catch{return route.fulfill({status:404,body:''});}
});

const candidateRecipes=Array.from({length:100},(_,i)=>({...recipes[i%3],recipe_id:String(i+1),document_id:String(i+1)}));
let eligibilityCalls=0;let delayed=false;
await page.route('**/content/eligibility/**',async route=>{
 const body=route.request().postDataJSON();eligibilityCalls++;
 assert.equal(body.local_only,true);
 if(delayed)await new Promise(resolve=>setTimeout(resolve,250));
 try{return await route.fulfill({json:{schema_version:'recipe-generation-v11',auto_completed:true,local_only:true,eligibility_id:'d'.repeat(64),generation_context:{query:body.query,recipe_ids:body.recipe_ids},qualified_recipe_ids:candidateRecipes.slice(0,20).map(r=>r.recipe_id),recipes:candidateRecipes,assessments:candidateRecipes.map((r,i)=>({recipe_id:r.recipe_id,status:i<96?'pass':'not_checked',checks:i===0?[{kind:'dish_name',role:'required',name:'beef soup',decision:'pass',source:'local',evidence:[r.name],reason:'Dish-name words matched.'},{kind:'dish_type',role:'required',name:'soup',decision:'pass',source:'local',evidence:[r.name],reason:'Explicit dish type.'}]:[]})),constraint_counts:{pass:96,fail:0,unknown:0,not_checked:4},eligibility_stats:{target:20,stop_reason:'enough_qualified_candidates',batches:0},check_ms:4,warnings:[],model_calls:[]}});}catch{}
});
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();
await page.locator('#stage-intent > .stage-handoff button').click();await page.locator('#submit-button').click();
const advance=page.locator('#stage-retrieval .stage-handoff button');await advance.filter({hasText:'Continue to generation'}).waitFor();
assert.match(await page.locator('#stage-retrieval .stage-handoff').innerText(),/96 qualified locally/);assert.equal(eligibilityCalls,1);assert.equal(generations.length,0);
assert.equal(await page.locator('[data-stage=check]').getAttribute('data-state'),'complete');
await page.screenshot({path:'/tmp/local-auto-check-desktop.png',fullPage:true});
await advance.click();assert.equal(await page.locator('#stage-generation').isVisible(),true);await page.locator('#generate-content').click();await page.locator('.generated-recipe').waitFor();assert.equal(generations.length,1);assert.equal(eligibilityCalls,1);
await page.locator('[data-stage=check]').click();assert.match(await page.locator('#stage-check > .stage-handoff').innerText(),/96 qualified · Top 20 selected/);
const qualified=page.locator('.check-outcome-group[data-outcome=pass]');await qualified.locator(':scope > summary').click();await qualified.locator('.check-recipe-evidence > summary').first().click();assert.match(await qualified.locator('.check-recipe').first().innerText(),/Dish name and type describe the same target/);await qualified.locator('.check-recipe').first().screenshot({path:'/tmp/dish-identity-check-group.png'});await qualified.locator(':scope > summary').click();
await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/local-auto-check-mobile.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
await page.locator('#user-query').fill('A new query');assert.equal(await page.locator('[data-stage=generation]').isDisabled(),true);assert.equal(await page.locator('#stage-check > .stage-handoff').isVisible(),false);
assert.deepEqual(errors,[]);await browser.close();console.log('Local completion browser: zero explicit checks, direct generation, counts, state invalidation, desktop/mobile passed.');
